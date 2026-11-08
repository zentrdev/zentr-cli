// Shared browser/CLI protocol. Existing v1/v2 ciphertext remains readable.
const encoder = new TextEncoder()
const counters = new WeakMap()
const receivedNonces = new WeakMap()
export const CHUNK_SIZE = 32 * 1024 * 1024
export const makeKey = async () => {
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt'])
  counters.set(key, { prefix: crypto.getRandomValues(new Uint8Array(8)), next: 0 })
  return key
}
export const encrypt = async (key, plaintext, context) => {
  const state = counters.get(key)
  // Imported keys are decrypt-only; never restart a nonce counter for a key.
  if (!state || state.next > 0xffffffff) throw new Error('Encryption nonce sequence exhausted or uninitialized')
  const iv = new Uint8Array(12)
  iv.set(state.prefix)
  new DataView(iv.buffer).setUint32(8, state.next++)
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: encoder.encode(context), tagLength: 128 }, key, plaintext))
  const result = new Uint8Array(12 + ciphertext.length)
  result.set(iv); result.set(ciphertext, 12)
  return result
}
export const decrypt = async (key, payload, context) => {
  if (payload.byteLength < 29) throw new Error('Encrypted data is incomplete')
  const nonce = Array.from(payload.slice(0, 12), b => b.toString(16).padStart(2, '0')).join('')
  let seen = receivedNonces.get(key)
  if (!seen) { seen = new Map(); receivedNonces.set(key, seen) }
  if (seen.has(nonce) && seen.get(nonce) !== context) throw new Error('Reused encryption nonce')
  seen.set(nonce, context)
  return new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: payload.slice(0, 12), additionalData: encoder.encode(context), tagLength: 128 }, key, payload.slice(12)))
}
export const manifestDigest = async (bytes) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('')
export const validateManifest = (manifest, info) => {
  if (![undefined, 1, 2, 3].includes(manifest.version)) throw new Error('Unsupported encrypted manifest')
  const files = Array.isArray(manifest.files) ? manifest.files : [{ name: manifest.name, type: manifest.type, size: info.originalSize, startChunk: 0, chunkCount: info.chunkCount }]
  if (!files.length || files.length > 20 || !Number.isSafeInteger(info.originalSize) || info.originalSize > 10 * 1024 ** 3 || !Number.isSafeInteger(info.chunkCount) || info.chunkCount > 512) throw new Error('Invalid encrypted manifest')
  let next = 0, size = 0
  const identifiers = new Set()
  for (const file of files) {
    if (typeof file.name !== 'string' || file.name.length > (manifest.version === 3 ? 180 : 1024) || typeof file.type !== 'string' || file.type.length > 255 || !Number.isSafeInteger(file.size) || file.size < 1 || file.startChunk !== next || file.chunkCount !== Math.ceil(file.size / CHUNK_SIZE)) throw new Error('Invalid encrypted manifest')
    if (manifest.version === 3) {
      if (!/^[a-f0-9]{32}$/.test(file.id) || identifiers.has(file.id)) throw new Error('Invalid file identifier')
      identifiers.add(file.id)
    }
    next += file.chunkCount; size += file.size
  }
  if (next !== info.chunkCount || size !== info.originalSize) throw new Error('Incomplete encrypted manifest')
  return files
}
export const chunkContext = (version, digest, file, localIndex, total) => {
  if (!Number.isSafeInteger(localIndex) || localIndex < 0 || localIndex >= file.chunkCount) throw new Error('Invalid chunk index')
  const index = file.startChunk + localIndex
  const size = Math.min(CHUNK_SIZE, file.size - localIndex * CHUNK_SIZE)
  return version === 3 ? `zentr-drop:file:v3:${digest}:${file.id}:${index}:${total}:${size}` : `zentr-drop:file:v1:${index}:${total}`
}
export const verifyChunk = (file, localIndex, plaintext) => {
  if (plaintext.byteLength !== Math.min(CHUNK_SIZE, file.size - localIndex * CHUNK_SIZE)) throw new Error('Encrypted chunk length does not match manifest')
  return plaintext
}
// Fragments are retained locally, never sent to the shortening endpoint.
export const splitShortLink = (value) => {
  const url = new URL(value)
  const fragment = url.hash
  url.hash = ''
  return { url: url.href, fragment }
}
