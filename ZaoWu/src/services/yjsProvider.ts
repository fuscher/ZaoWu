import * as Y from 'yjs'
import { Awareness, applyAwarenessUpdate, encodeAwarenessUpdate } from 'y-protocols/awareness'
import type { WSMessage, WSMessageType } from '@/types'

export interface YjsProviderOptions {
  roomId: string
  wsUrl: string
  userId: string
  onMessage?: (message: WSMessage) => void
  onStatusChange?: (status: 'connecting' | 'connected' | 'disconnected' | 'error') => void
  onSync?: (synced: boolean) => void
}

export class YjsProvider {
  roomId: string
  userId: string
  doc: Y.Doc
  awareness: Awareness

  private ws: WebSocket | null = null
  private wsUrl: string
  private onMessage?: (message: WSMessage) => void
  private onStatusChange?: (status: 'connecting' | 'connected' | 'disconnected' | 'error') => void
  private onSync?: (synced: boolean) => void
  private updateHandler: (update: Uint8Array, origin: unknown) => void

  constructor(options: YjsProviderOptions) {
    this.roomId = options.roomId
    this.userId = options.userId
    this.wsUrl = options.wsUrl
    this.onMessage = options.onMessage
    this.onStatusChange = options.onStatusChange
    this.onSync = options.onSync

    this.doc = new Y.Doc()
    this.awareness = new Awareness(this.doc)

    this.updateHandler = (update, origin) => {
      if (origin === this) return
      this.sendYjsUpdate(update)
    }
    this.doc.on('update', this.updateHandler)
  }

  connect() {
    if (this.ws) return
    this.setStatus('connecting')
    try {
      this.ws = new WebSocket(this.wsUrl)
    } catch (err) {
      this.setStatus('error')
      return
    }

    this.ws.binaryType = 'arraybuffer'

    this.ws.onopen = () => {
      this.setStatus('connected')
      this.onSync?.(false)
    }

    this.ws.onmessage = (event) => {
      let message: WSMessage
      try {
        message = JSON.parse(event.data as string)
      } catch {
        return
      }
      this.handleServerMessage(message)
    }

    this.ws.onclose = () => {
      this.ws = null
      this.setStatus('disconnected')
    }

    this.ws.onerror = () => {
      this.setStatus('error')
    }
  }

  disconnect() {
    this.doc.off('update', this.updateHandler)
    this.awareness.destroy()
    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        // ignore
      }
      this.ws = null
    }
    this.setStatus('disconnected')
  }

  send(type: WSMessageType, payload: unknown) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    const message: WSMessage = {
      type,
      roomId: this.roomId,
      userId: this.userId,
      payload,
      timestamp: Date.now(),
    }
    this.ws.send(JSON.stringify(message))
  }

  private sendYjsUpdate(update: Uint8Array) {
    const base64 = arrayBufferToBase64(update)
    this.send('yjs_update', { update: base64 })
  }

  private handleServerMessage(message: WSMessage) {
    this.onMessage?.(message)

    if (message.type === 'room_state') {
      const payload = message.payload as {
        users?: unknown[]
        yjsUpdate?: string
        permissions?: unknown
      }
      if (payload.yjsUpdate) {
        const update = base64ToUint8Array(payload.yjsUpdate)
        Y.applyUpdate(this.doc, update, this)
      }
      this.onSync?.(true)
      return
    }

    if (message.type === 'yjs_update') {
      const updateBase64 = (message.payload as { update?: string }).update
      if (updateBase64) {
        const update = base64ToUint8Array(updateBase64)
        Y.applyUpdate(this.doc, update, this)
      }
      return
    }

    if (message.type === 'awareness_update') {
      const awarenessUpdate = (message.payload as { update?: string }).update
      if (awarenessUpdate) {
        applyAwarenessUpdate(this.awareness, base64ToUint8Array(awarenessUpdate), this)
      }
    }
  }

  private setStatus(status: 'connecting' | 'connected' | 'disconnected' | 'error') {
    this.onStatusChange?.(status)
  }
}

function arrayBufferToBase64(buffer: Uint8Array): string {
  let binary = ''
  const len = buffer.byteLength
  for (let i = 0; i < len; i++) {
    const byte = buffer[i]
    if (byte !== undefined) {
      binary += String.fromCharCode(byte)
    }
  }
  return btoa(binary)
}

function base64ToUint8Array(base64: string): Uint8Array {
  const binary = atob(base64)
  const len = binary.length
  const bytes = new Uint8Array(len)
  for (let i = 0; i < len; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}
