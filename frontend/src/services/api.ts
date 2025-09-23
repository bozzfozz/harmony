import axios from "axios";

const DEFAULT_BASE_URL = "http://localhost:8000";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL,
  timeout: 15000
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      error.message = error.response.data?.detail ?? error.message;
    }
    return Promise.reject(error);
  }
);

export default api;
