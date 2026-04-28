import client from './client'

export async function listDatabases() {
  const res = await client.get('/databases')
  return res.data
}

export async function provisionDB(data) {
  const res = await client.post('/databases', data)
  return res.data
}

export async function getDatabase(id) {
  const res = await client.get(`/databases/${id}`)
  return res.data
}

export async function deprovisionDB(id) {
  await client.delete(`/databases/${id}`)
}
