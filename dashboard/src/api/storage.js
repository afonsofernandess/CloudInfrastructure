import client from './client'

export async function listFiles() {
  const res = await client.get('/storage/files')
  return res.data
}

export async function uploadFile(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await client.post('/storage/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const pct = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        onProgress(pct)
      }
    },
  })
  return res.data
}

export async function downloadFile(filename) {
  const res = await client.get(`/storage/download/${encodeURIComponent(filename)}`, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function deleteFile(filename) {
  await client.delete(`/storage/files/${encodeURIComponent(filename)}`)
}
