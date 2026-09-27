import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './styles/base.css'
import './styles/pages.css'
import './styles/discussions.css'
import './styles/editor.css'
import './styles/blocks.css'
import './styles/analysis.css'

const root = document.getElementById('root')
if (!root) throw new Error('Missing root element')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
