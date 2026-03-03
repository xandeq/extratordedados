import axios from 'axios'

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.extratordedados.com.br'

const api = axios.create({
  baseURL: API_URL,
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('token')
      localStorage.removeItem('user_id')
      window.location.href = '/login/'
    }
    return Promise.reject(error)
  }
)

export default api
