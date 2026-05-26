import client from './client'

export async function listVMs() {
  const res = await client.get('/compute/vms')
  return res.data
}

export async function createVM(data) {
  const res = await client.post('/compute/vms', data)
  return res.data
}

export async function getVM(id) {
  const res = await client.get(`/compute/vms/${id}`)
  return res.data
}

export async function destroyVM(id) {
  await client.delete(`/compute/vms/${id}`)
}

export async function getClusterStatus() {
  const res = await client.get('/compute/status')
  return res.data
}

export async function prewarmVM() {
  const res = await client.post('/compute/prewarm')
  return res.data
}
