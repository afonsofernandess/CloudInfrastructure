import client from './client'

export async function listDatabases() {
  const res = await client.get('/databases')
  return res.data
}

export async function provisionDB(data) {
  if (data.is_cluster) {
    const payload = {
      cluster_name: data.name,
      db_name: data.db_name || undefined,
      replicas: data.replicas || 1
    }
    const res = await client.post('/loadbalancer/databases/cluster', payload)
    return res.data
  } else {
    const res = await client.post('/databases', {
      name: data.name,
      db_name: data.db_name || undefined,
      vm_id: data.vm_id || undefined
    })
    return res.data
  }
}

export async function getDatabase(id) {
  const res = await client.get(`/databases/${id}`)
  return res.data
}

export async function deprovisionDB(id) {
  await client.delete(`/databases/${id}`)
}

export async function deleteCluster(clusterName) {
  await client.delete(`/loadbalancer/databases/cluster/${clusterName}`)
}

export async function restartDB(id) {
  await client.post(`/databases/${id}/restart`)
}
