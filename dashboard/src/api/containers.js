import client from './client'

export async function listContainers() {
  const res = await client.get('/containers')
  return res.data
}

export async function launchContainer(data) {
  if (data.is_scale_group) {
    const payload = {
      name: data.name,
      image: data.image,
      replicas: data.replicas || 1,
      container_port: data.container_port || "80/tcp",
      env: data.env || {}
    }
    const res = await client.post('/loadbalancer/containers/scale', payload)
    return res.data
  } else {
    const res = await client.post('/containers', data)
    return res.data
  }
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

export async function getContainerStats(id) {
  const res = await client.get(`/containers/${id}/stats`)
  return res.data
}
