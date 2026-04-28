import client from './client'

export async function login(username, password) {
  const res = await client.post('/auth/login', { username, password })
  return res.data
}

export async function register(username, email, password) {
  const res = await client.post('/auth/register', { username, email, password })
  return res.data
}

export async function getMe() {
  const res = await client.get('/auth/me')
  return res.data
}

export async function updateMe(data) {
  const res = await client.put('/auth/me', data)
  return res.data
}

export async function deleteMe() {
  const res = await client.delete('/auth/me')
  return res.data
}
