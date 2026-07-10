import { ref, computed } from 'vue'

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000]
const HEARTBEAT_INTERVAL = 30000
const HEARTBEAT_TIMEOUT = 35000

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting' | 'error'

export interface UseWebSocketOptions {
  url: string | (() => string)
  protocols?: string | string[]
  autoReconnect?: boolean
  heartbeat?: boolean
  onMessage?: (event: MessageEvent) => void
  onOpen?: (event: Event) => void
  onClose?: (event: CloseEvent) => void
  onError?: (event: Event) => void
}

export function useWebSocket(options: UseWebSocketOptions) {
  const status = ref<WebSocketStatus>('disconnected')
  const error = ref<string>('')

  let ws: WebSocket | null = null
  let reconnectAttempt = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let pongTimer: ReturnType<typeof setTimeout> | null = null
  let manuallyClosed = false

  const isConnected = computed(() => status.value === 'connected')

  function resolveUrl(): string {
    return typeof options.url === 'function' ? options.url() : options.url
  }

  function clearTimers() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
    if (pongTimer) {
      clearTimeout(pongTimer)
      pongTimer = null
    }
  }

  function send(data: string | Blob | ArrayBuffer | ArrayBufferView) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(data as string | Blob | ArrayBuffer)
      return true
    }
    return false
  }

  function sendJson(payload: unknown) {
    return send(JSON.stringify(payload))
  }

  function scheduleReconnect() {
    if (!options.autoReconnect || manuallyClosed) return
    status.value = 'reconnecting'
    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)]
    reconnectTimer = setTimeout(() => {
      reconnectAttempt += 1
      connect()
    }, delay)
  }

  function startHeartbeat() {
    if (!options.heartbeat) return
    heartbeatTimer = setInterval(() => {
      sendJson({ type: 'ping', timestamp: Date.now() })
      pongTimer = setTimeout(() => {
        // No pong received; close and reconnect
        ws?.close()
      }, HEARTBEAT_TIMEOUT)
    }, HEARTBEAT_INTERVAL)
  }

  function connect() {
    if (ws) {
      try {
        ws.close()
      } catch {
        // ignore
      }
      ws = null
    }

    manuallyClosed = false
    status.value = 'connecting'
    error.value = ''

    try {
      const url = resolveUrl()
      ws = new WebSocket(url, options.protocols)
    } catch (err) {
      status.value = 'error'
      error.value = String(err)
      scheduleReconnect()
      return
    }

    ws.onopen = (event) => {
      reconnectAttempt = 0
      status.value = 'connected'
      startHeartbeat()
      options.onOpen?.(event)
    }

    ws.onmessage = (event) => {
      if (event.data === JSON.stringify({ type: 'pong' })) {
        if (pongTimer) {
          clearTimeout(pongTimer)
          pongTimer = null
        }
      }
      options.onMessage?.(event)
    }

    ws.onclose = (event) => {
      clearTimers()
      status.value = 'disconnected'
      options.onClose?.(event)
      scheduleReconnect()
    }

    ws.onerror = (event) => {
      error.value = 'websocket error'
      status.value = 'error'
      options.onError?.(event)
    }
  }

  function disconnect() {
    manuallyClosed = true
    clearTimers()
    if (ws) {
      try {
        ws.close()
      } catch {
        // ignore
      }
      ws = null
    }
    status.value = 'disconnected'
  }

  return {
    status,
    error,
    isConnected,
    connect,
    disconnect,
    send,
    sendJson,
  }
}
