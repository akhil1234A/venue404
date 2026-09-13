import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect, useRef, useCallback } from 'react'
import { createClient, chatEndpoints } from '@venue404/api-client'

export interface ChatMessage {
  id: string
  booking_id: string
  sender_id: string
  message: string
  created_at: string
  read_at: string | null
  status?: 'sending' | 'sent' | 'failed'
}

export interface TypingUser {
  userId: string
  userName?: string
}

type WsEvent =
  | { type: 'connected'; payload?: { booking_id: string } }
  | { type: 'message_created' | 'message_sent'; payload: ChatMessage & { client_msg_id?: string } }
  | { type: 'messages_read'; payload?: { reader_id?: string; booking_id?: string } }
  | { type: 'typing_start' | 'typing_stop'; payload?: { user_id?: string; user_name?: string; booking_id?: string } }
  | { type: 'error'; payload?: { message?: string; client_msg_id?: string } }
  | { type: 'pong'; payload?: Record<string, unknown> }

function mergeById(existing: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const map = new Map<string, ChatMessage>()
  for (const msg of existing) map.set(msg.id, msg)
  for (const msg of incoming) {
    const prev = map.get(msg.id)
    map.set(msg.id, prev ? { ...prev, ...msg, status: msg.status ?? prev.status ?? 'sent' } : msg)
  }
  return Array.from(map.values()).sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )
}

function upsertMessage(list: ChatMessage[], message: ChatMessage): ChatMessage[] {
  return mergeById(list, [message])
}

export interface UseChatReturn {
  messages: ChatMessage[]
  isLoading: boolean
  isError: boolean
  isConnected: boolean
  sendError: string | null
  sendMessage: (message: string) => Promise<void>
  retryMessage: (messageId: string) => Promise<void>
  markRead: () => Promise<void>
  refetch: () => void
  typingUsers: TypingUser[]
  sendTyping: () => void
}

export function useChat(bookingId: string, currentUserId?: string): UseChatReturn {
  const queryClient = useQueryClient()

  const [isConnected, setIsConnected] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sendError, setSendError] = useState<string | null>(null)
  const [typingUsers, setTypingUsers] = useState<TypingUser[]>([])

  useEffect(() => {
    setMessages([])
    setSendError(null)
    setTypingUsers([])
  }, [bookingId])

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const pingIntervalRef = useRef<ReturnType<typeof setInterval>>()
  const reconnectAttemptRef = useRef(0)
  const currentUserIdRef = useRef(currentUserId)
  const lastTypingSentRef = useRef(0)
  const typingTimeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  useEffect(() => {
    currentUserIdRef.current = currentUserId
  }, [currentUserId])

  const messageQuery = useQuery({
    queryKey: ['chat-messages', bookingId],
    queryFn: () => chatEndpoints(createClient()).listMessages(bookingId) as Promise<ChatMessage[]>,
    enabled: !!bookingId,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    if (messageQuery.data) {
      setMessages((prev) => {
        const pending = prev.filter(
          (m) => (m.status === 'sending' || m.status === 'failed') && m.booking_id === bookingId,
        )
        return mergeById(messageQuery.data as ChatMessage[], pending)
      })
    }
  }, [messageQuery.data, bookingId])

  const invalidateConversations = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['chat-conversations'] })
    queryClient.invalidateQueries({ queryKey: ['owner-chat-conversations'] })
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }, [queryClient])

  const markRead = useCallback(async () => {
    if (!bookingId) return
    try {
      await chatEndpoints(createClient()).markRead(bookingId)
      invalidateConversations()
    } catch {
      // non-fatal
    }
  }, [bookingId, invalidateConversations])

  // Mark as read when conversation opens / history loads
  useEffect(() => {
    if (!bookingId || !messageQuery.data) return
    void markRead()
  }, [bookingId, messageQuery.dataUpdatedAt, markRead])

  const sendTyping = useCallback(() => {
    const now = Date.now()
    if (now - lastTypingSentRef.current < 3000) return // Throttle to 1 per 3s
    lastTypingSentRef.current = now

    const socket = wsRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'typing_start' }))
    }
  }, [])

  useEffect(() => {
    if (!bookingId) return

    let cancelled = false

    const clearPing = () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = undefined
      }
    }

    const scheduleReconnect = () => {
      if (cancelled) return
      const attempt = reconnectAttemptRef.current
      const delay = Math.min(1000 * 2 ** attempt, 15000)
      reconnectAttemptRef.current = attempt + 1
      reconnectTimeoutRef.current = setTimeout(connect, delay)
    }

    const handleIncoming = (raw: string) => {
      let data: WsEvent
      try {
        data = JSON.parse(raw)
      } catch {
        return
      }

      if (data.type === 'message_created' || data.type === 'message_sent') {
        const payload: ChatMessage = { ...data.payload, status: 'sent' }
        const clientMsgId = data.payload?.client_msg_id

        setMessages((prev) => {
          if (clientMsgId) {
            const withoutOptimistic = prev.filter((m) => m.id !== clientMsgId)
            return upsertMessage(withoutOptimistic, payload)
          }
          const withoutOptimistic = prev.filter(
            (m) =>
              !(
                m.status === 'sending' &&
                m.message === payload.message &&
                (m.sender_id === payload.sender_id || m.id.startsWith('temp-'))
              ),
          )
          return upsertMessage(withoutOptimistic, payload)
        })

        // Also clear typing indicator for the user who just sent a message
        if (payload.sender_id) {
          setTypingUsers((prev) => prev.filter((u) => u.userId !== payload.sender_id))
          const existing = typingTimeoutsRef.current.get(payload.sender_id)
          if (existing) {
            clearTimeout(existing)
            typingTimeoutsRef.current.delete(payload.sender_id)
          }
        }

        if (data.type === 'message_created') {
          void markRead()
        }
        invalidateConversations()
      } else if (data.type === 'messages_read') {
        const readerId = data.payload?.reader_id
        setMessages((prev) =>
          prev.map((m) => {
            if (readerId && m.sender_id === currentUserIdRef.current && !m.read_at) {
              return { ...m, read_at: new Date().toISOString() }
            }
            if (!readerId && !m.read_at && m.sender_id === currentUserIdRef.current) {
              return { ...m, read_at: new Date().toISOString() }
            }
            return m
          }),
        )
      } else if (data.type === 'typing_start') {
        const uid = data.payload?.user_id
        const uname = data.payload?.user_name
        if (uid && uid !== currentUserIdRef.current) {
          setTypingUsers((prev) => {
            const exists = prev.some((u) => u.userId === uid)
            if (exists) {
              return prev.map((u) =>
                u.userId === uid ? { userId: uid, userName: uname || u.userName } : u,
              )
            }
            return [...prev, { userId: uid, userName: uname }]
          })
          const existing = typingTimeoutsRef.current.get(uid)
          if (existing) clearTimeout(existing)
          typingTimeoutsRef.current.set(
            uid,
            setTimeout(() => {
              setTypingUsers((prev) => prev.filter((u) => u.userId !== uid))
              typingTimeoutsRef.current.delete(uid)
            }, 5000),
          )
        }
      } else if (data.type === 'typing_stop') {
        const uid = data.payload?.user_id
        if (uid) {
          setTypingUsers((prev) => prev.filter((u) => u.userId !== uid))
          const existing = typingTimeoutsRef.current.get(uid)
          if (existing) {
            clearTimeout(existing)
            typingTimeoutsRef.current.delete(uid)
          }
        }
      } else if (data.type === 'error') {
        setSendError(data.payload?.message || 'Chat error')
        const clientMsgId = data.payload?.client_msg_id
        if (clientMsgId) {
          setMessages((prev) =>
            prev.map((m) => (m.id === clientMsgId ? { ...m, status: 'failed' as const } : m)),
          )
        }
      }
    }

    const connect = async () => {
      if (cancelled) return
      try {
        if (wsRef.current) {
          wsRef.current.onclose = null
          wsRef.current.close()
          wsRef.current = null
        }

        const websocket = await chatEndpoints(createClient()).connectWebSocket(bookingId)
        if (cancelled) {
          websocket.close()
          return
        }

        wsRef.current = websocket

        websocket.onopen = () => {
          if (cancelled) return
          setIsConnected(true)
          reconnectAttemptRef.current = 0
          clearPing()
          pingIntervalRef.current = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'ping' }))
            }
          }, 25000)
          queryClient.invalidateQueries({ queryKey: ['chat-messages', bookingId] })
        }

        websocket.onclose = () => {
          if (cancelled) return
          setIsConnected(false)
          clearPing()
          scheduleReconnect()
          setMessages((prev) =>
            prev.map((m) => (m.status === 'sending' ? { ...m, status: 'failed' as const } : m)),
          )
        }

        websocket.onerror = () => {
          // onclose follows
        }

        websocket.onmessage = (event) => handleIncoming(event.data)
      } catch (e) {
        console.error('Chat WebSocket error:', e)
        if (!cancelled) {
          setIsConnected(false)
          scheduleReconnect()
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      clearPing()
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
      typingTimeoutsRef.current.forEach((t) => clearTimeout(t))
      typingTimeoutsRef.current.clear()
      setIsConnected(false)
    }
  }, [bookingId, invalidateConversations, markRead, queryClient])

  const sendMessage = useCallback(
    async (message: string) => {
      const trimmed = message.trim()
      if (!trimmed || !bookingId) return

      setSendError(null)
      const userId = currentUserIdRef.current || ''
      const tempId = `temp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

      if (userId) {
        setMessages((prev) =>
          upsertMessage(prev, {
            id: tempId,
            booking_id: bookingId,
            sender_id: userId,
            message: trimmed,
            created_at: new Date().toISOString(),
            read_at: null,
            status: 'sending',
          }),
        )
      }

      const socket = wsRef.current
      if (socket && socket.readyState === WebSocket.OPEN) {
        try {
          socket.send(
            JSON.stringify({ type: 'send_message', message: trimmed, client_msg_id: tempId }),
          )
          return
        } catch {
          // fall through to REST
        }
      }

      try {
        const created = (await chatEndpoints(createClient()).sendMessage(
          bookingId,
          trimmed,
        )) as ChatMessage
        setMessages((prev) => {
          const withoutTemp = prev.filter((m) => m.id !== tempId)
          return upsertMessage(withoutTemp, { ...created, status: 'sent' })
        })
        invalidateConversations()
        queryClient.invalidateQueries({ queryKey: ['chat-messages', bookingId] })
      } catch (e: any) {
        console.error('Failed to send message:', e)
        const isRateLimit =
          e?.response?.status === 429 ||
          e?.status === 429 ||
          e?.message?.includes('slow down') ||
          e?.message?.includes('too quickly')
        setSendError(
          isRateLimit
            ? "You're sending messages too quickly. Please slow down."
            : 'Failed to send message. Please try again.',
        )
        setMessages((prev) =>
          prev.map((m) => (m.id === tempId ? { ...m, status: 'failed' as const } : m)),
        )
      }
    },
    [bookingId, invalidateConversations, queryClient],
  )

  const retryMessage = useCallback(
    async (messageId: string) => {
      const msg = messages.find((m) => m.id === messageId && m.status === 'failed')
      if (!msg) return

      setMessages((prev) => prev.filter((m) => m.id !== messageId))
      await sendMessage(msg.message)
    },
    [messages, sendMessage],
  )

  return {
    messages,
    isLoading: messageQuery.isLoading,
    isError: messageQuery.isError,
    isConnected,
    sendError,
    sendMessage,
    retryMessage,
    markRead,
    refetch: messageQuery.refetch,
    typingUsers,
    sendTyping,
  }
}
