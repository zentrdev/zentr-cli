import { test } from 'node:test'
import assert from 'node:assert/strict'
import { makeKey, encrypt, decrypt, validateManifest, chunkContext, manifestDigest, splitShortLink } from '../src/zentr_cli/vendor/drop/crypto.mjs'

test('browser-compatible AES-GCM round trip and tamper rejection', async () => {
  const key = await makeKey(), plain = new TextEncoder().encode('Zentr CLI test')
  const sealed = await encrypt(key, plain, 'zentr-drop:text:v1')
  assert.deepEqual(await decrypt(key, sealed, 'zentr-drop:text:v1'), plain)
  const changed = sealed.slice(); changed[changed.length - 1] ^= 1
  await assert.rejects(decrypt(key, changed, 'zentr-drop:text:v1'))
  await assert.rejects(decrypt(key, sealed, 'wrong-context'))
})
test('nonce changes for each message', async () => {
  const key = await makeKey(), plain = new Uint8Array([1])
  const a = await encrypt(key, plain, 'a'), b = await encrypt(key, plain, 'b')
  assert.notDeepEqual(a.slice(0, 12), b.slice(0, 12))
})
test('file manifests bind chunk identity and reject inconsistent sizes', async () => {
  const file = { id: 'a'.repeat(32), name: 'test.txt', type: 'text/plain', size: 3, startChunk: 0, chunkCount: 1 }
  const manifest = { version: 3, files: [file] }
  assert.deepEqual(validateManifest(manifest, { originalSize: 3, chunkCount: 1 }), [file])
  assert.throws(() => validateManifest(manifest, { originalSize: 4, chunkCount: 1 }))
  const digest = await manifestDigest(new TextEncoder().encode(JSON.stringify(manifest)))
  assert.equal(chunkContext(3, digest, file, 0, 1), `zentr-drop:file:v3:${digest}:${file.id}:0:1:3`)
  assert.throws(() => chunkContext(3, digest, file, 1, 1))
})
test('shortening does not transmit key fragments', () => {
  assert.deepEqual(splitShortLink('https://drop.zentr.dev/f/ABCDE#private-key'),
    { url: 'https://drop.zentr.dev/f/ABCDE', fragment: '#private-key' })
})
