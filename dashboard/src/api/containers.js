import client from './client'

export async function listContainers() {
  const res = await client.get('/containers')
  return res.data
}

export async function launchContainer(data) {
  const res = await client.post('/containers', data)
  return res.data
}

export async function getContainer(id) {
  const res = await client.get(`/containers/${id}`)
  return res.data
}

export async function startContainer(id) {
  const res = await client.post(`/containers/${id}/start`)
  return res.data
}

export async function stopContainer(id) {
  const res = await client.post(`/containers/${id}/stop`)
  return res.data
}

export async function removeContainer(id) {
  await client.delete(`/containers/${id}`)
}

export async function getContainerLogs(id, tail = 100) {
  const res = await client.get(`/containers/${id}/logs`, { params: { tail } })
  return res.data
}
