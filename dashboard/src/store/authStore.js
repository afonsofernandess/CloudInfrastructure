import { create } from 'zustand'

const useAuthStore = create((set) => ({
  token: localStorage.getItem('cloud_token') || null,
  user: null,

  setAuth: (token, user) => {
    localStorage.setItem('cloud_token', token)
    set({ token, user })
  },

  setUser: (user) => {
    set({ user })
  },

  logout: () => {
    localStorage.removeItem('cloud_token')
    set({ token: null, user: null })
  },
}))

export default useAuthStore
