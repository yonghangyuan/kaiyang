import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './globals'  // attach window.loadEventItems, window.tianshuPopup
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>
)
