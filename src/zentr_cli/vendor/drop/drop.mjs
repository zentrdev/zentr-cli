#!/usr/bin/env node
import { randomBytes } from 'node:crypto'
import { open, stat, mkdir, unlink, link } from 'node:fs/promises'
import { makeKey, encrypt as seal, decrypt as unseal, manifestDigest, validateManifest, chunkContext, splitShortLink } from './crypto.mjs'
import { basename, resolve, join } from 'node:path'

const CHUNK = 32 * 1024 * 1024, PART = 4 * 1024 * 1024
const origin = new URL(process.env.DROP_ORIGIN || 'https://drop.zentr.dev').origin
const help = `Zentr Drop

  zentr drop upload <file...>         Upload up to 20 files, encrypted
  zentr drop text <message>           Share encrypted text
  echo "hello" | zentr drop text      Share text from stdin
  zentr drop get '<full drop URL>'    Download files or print decrypted text
  zentr drop get '<URL>' -o <folder>  Download files into a folder
  zentr drop shorten '<URL>'          Create a short URL (not encrypted)
  zentr drop status <code or URL>     Show drop status
  zentr drop help                    Show this help

Quote share URLs to preserve their #decryption key. Existing files are never overwritten.
Upload links go to stdout; progress goes to stderr.
`
const encrypt = async (data, key, context) => Buffer.from(await seal(key, data, context))
const decrypt = async (data, key, context) => Buffer.from(await unseal(key, data, context))
const encodedKey = async key => Buffer.from(await crypto.subtle.exportKey('raw', key)).toString('base64url')
async function request(path, options = {}, binary = false) {
  const response = await fetch(origin + path, { ...options, redirect: 'error', signal: AbortSignal.timeout(300000) })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message || `HTTP ${response.status}`)
  }
  return binary ? Buffer.from(await response.arrayBuffer()) : response.json()
}
const jsonPost = (path, body) => request(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
function parseDrop(value) {
  if (/^[A-Za-z0-9_-]{5}$/.test(value || '')) return { id: value }
  const url = new URL(value)
  if (url.origin !== origin || !/^\/[ft]\/[A-Za-z0-9_-]{5}$/.test(url.pathname)) throw new Error('Use a full file/text Drop URL')
  return { id: url.pathname.slice(3), key: url.hash.slice(1) }
}
async function upload(paths) {
  if (!paths.length || paths.length > 20) throw new Error('Choose 1–20 files')
  let count = 0, total = 0
  const files = [], sizes = []
  for (const path of paths) {
    const info = await stat(path)
    if (!info.isFile() || !info.size) throw new Error(`Not a nonempty file: ${path}`)
    const chunkCount = Math.ceil(info.size / CHUNK)
    files.push({ path, id: randomBytes(16).toString('hex'), name: basename(path).slice(0, 180), type: 'application/octet-stream', size: info.size, startChunk: count, chunkCount })
    for (let i = 0; i < chunkCount; i++) sizes.push(Math.min(CHUNK, info.size - i * CHUNK))
    count += chunkCount; total += info.size
  }
  if (count > 512 || total > 10 * 1024 ** 3) throw new Error('Drop exceeds the upload limit')
  const key = await makeKey()
  const manifestBytes = Buffer.from(JSON.stringify({ version: 3, files: files.map(({ path, ...file }) => file) }))
  const digest = await manifestDigest(manifestBytes)
  const descriptor = await encrypt(manifestBytes, key, 'zentr-drop:descriptor:v1')
  const session = await jsonPost('/api/drop/file/init', { size: total, chunkCount: count, chunkSizes: sizes, descriptor: descriptor.toString('base64url') })
  let completed = 0
  for (const file of files) {
    const handle = await open(file.path, 'r')
    try {
      for (let i = 0; i < file.chunkCount; i++) {
        const index = file.startChunk + i, plain = Buffer.alloc(sizes[index])
        let offset = 0
        while (offset < plain.length) {
          const { bytesRead } = await handle.read(plain, offset, plain.length - offset, i * CHUNK + offset)
          if (!bytesRead) throw new Error(`File changed during upload: ${file.name}`)
          offset += bytesRead
        }
        const encrypted = await encrypt(plain, key, chunkContext(3, digest, file, i, count))
        const partCount = Math.ceil(encrypted.length / PART)
        let cursor = 0
        const results = await Promise.allSettled(Array.from({ length: Math.min(4, partCount) }, async () => {
          while (cursor < partCount) {
            const part = cursor++, bytes = encrypted.subarray(part * PART, (part + 1) * PART)
            await request(`/api/drop/file/${session.uploadId}/chunk/${index}/part/${part}`, { method: 'PUT', headers: { authorization: `Bearer ${session.uploadToken}`, 'content-type': 'application/octet-stream', 'x-zentr-part-count': String(partCount) }, body: bytes })
          }
        }))
        const failed = results.find(result => result.status === 'rejected')
        if (failed) throw failed.reason
        completed += plain.length
        process.stderr.write(`Uploading ${file.name}: ${Math.round(completed / total * 100)}%\n`)
      }
    } finally { await handle.close() }
  }
  const result = await request(`/api/drop/file/${session.uploadId}/complete`, { method: 'POST', headers: { authorization: `Bearer ${session.uploadToken}` } })
  console.log(`${result.url}#${await encodedKey(key)}`)
}
async function get(value, directory) {
  const drop = parseDrop(value)
  if (!/^[A-Za-z0-9_-]{43}$/.test(drop.key || '')) throw new Error('Downloading requires the full URL including its decryption key')
  const key = await crypto.subtle.importKey('raw', Buffer.from(drop.key, 'base64url'), 'AES-GCM', false, ['decrypt']), info = await request(`/api/status/${drop.id}`)
  if (!info.encrypted) throw new Error('This command requires an encrypted drop')
  if (info.type === 'text') {
    const data = await request(`/api/drop/${drop.id}/payload`, {}, true)
    process.stdout.write(await decrypt(data, key, 'zentr-drop:text:v1')); return
  }
  const manifestBytes = await decrypt(await request(`/api/drop/${drop.id}/descriptor`, {}, true), key, 'zentr-drop:descriptor:v1')
  const descriptor = JSON.parse(manifestBytes.toString())
  const digest = await manifestDigest(manifestBytes)
  const files = validateManifest(descriptor, info)
  if (!Array.isArray(files) || files.length < 1 || files.length > 20) throw new Error('Invalid file list')
  let next = 0, total = 0
  for (const file of files) {
    if (!Number.isSafeInteger(file.size) || file.size < 1 || file.startChunk !== next || file.chunkCount !== Math.ceil(file.size / CHUNK)) throw new Error('Invalid file layout')
    next += file.chunkCount; total += file.size
  }
  if (next !== info.chunkCount || total !== info.originalSize) throw new Error('Invalid file layout')
  const target = resolve(directory || '.')
  await mkdir(target, { recursive: true })
  for (const file of files) {
    const name = String(file.name || 'download').replace(/[\x00-\x1f\x7f/\\:]/g, '_').slice(0, 180)
    if (!name || /^\.+$/.test(name)) throw new Error('Invalid filename')
    const path = join(target, name), temporary = join(target, `.drop-${randomBytes(16).toString('hex')}.partial`), handle = await open(temporary, 'wx', 0o600)
    let saved = false
    try {
      for (let i = 0; i < file.chunkCount; i++) {
        const index = file.startChunk + i
        const plain = await decrypt(await request(`/api/drop/${drop.id}/chunk/${index}`, {}, true), key, chunkContext(descriptor.version, digest, file, i, info.chunkCount))
        if (plain.length !== Math.min(CHUNK, file.size - i * CHUNK)) throw new Error('Invalid decrypted file size')
        await handle.writeFile(plain)
      }
      await handle.sync()
      await link(temporary, path) // Atomic publish only after every chunk verifies; never overwrite.
      saved = true
    } finally { await handle.close(); await unlink(temporary).catch(() => {}) }
    console.log(path)
  }
}
async function main() {
  const [command, ...args] = process.argv.slice(2)
  if (!command || ['help', '--help', '-h'].includes(command)) return process.stdout.write(help)
  if (command === 'upload') return upload(args)
  if (command === 'text') {
    let plain = args.join(' ')
    if (!args.length) {
      if (process.stdin.isTTY) throw new Error('Provide text or pipe it through stdin')
      const parts = []; let size = 0
      for await (const part of process.stdin) { size += part.length; if (size > 1024 * 1024) throw new Error('Text exceeds 1 MiB'); parts.push(part) }
      plain = Buffer.concat(parts).toString('utf8')
    }
    if (!plain || Buffer.byteLength(plain) > 1024 * 1024) throw new Error('Text must contain 1 byte to 1 MiB')
    const key = await makeKey()
    const result = await request('/api/drop/text/encrypted', { method: 'POST', headers: { 'content-type': 'application/octet-stream' }, body: await encrypt(Buffer.from(plain), key, 'zentr-drop:text:v1') })
    return console.log(`${result.url}#${await encodedKey(key)}`)
  }
  if (command === 'get' && args[0] && (args.length === 1 || (args.length === 3 && args[1] === '-o'))) return get(args[0], args[2])
  if (command === 'shorten' && args.length === 1) {
    const target = splitShortLink(args[0])
    return console.log((await jsonPost('/api/link', { url: target.url })).url + target.fragment)
  }
  if (command === 'status' && args.length === 1) return console.log(JSON.stringify(await request(`/api/status/${parseDrop(args[0]).id}`), null, 2))
  throw new Error('Unknown command or arguments. Run zentr drop help')
}
main().catch(error => { console.error(`drop: ${error.code === 'EEXIST' ? 'Destination file already exists' : error.message}`); process.exitCode = 1 })
