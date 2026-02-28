export interface UserResponse {
  id: string
  email: string
  createdAt: string
}

export interface AuthResponse {
  token: string
  user: UserResponse
}

export interface Note {
  id: string
  title: string
  content: string
  tags: string[]
  createdAt: string
  updatedAt: string
}
