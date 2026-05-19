import { useEffect, useRef } from 'react'
import { Terminal } from 'xterm'
import { AttachAddon } from 'xterm-addon-attach'
import 'xterm/css/xterm.css'

export default function VMTerminal({ ip, onClose }) {
  const terminalRef = useRef(null)
  const xtermRef = useRef(null)

  useEffect(() => {
    if (!terminalRef.current) return

    const term = new Terminal({
      cursorBlink: true,
      theme: {
        background: '#0f172a', // slate-900
      },
      fontFamily: 'JetBrains Mono, Menlo, Monaco, "Courier New", monospace',
      fontSize: 14,
    })

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//localhost:8000/terminal/${ip}`
    const socket = new WebSocket(wsUrl)

    const attachAddon = new AttachAddon(socket)
    term.loadAddon(attachAddon)

    term.open(terminalRef.current)
    xtermRef.current = term

    socket.onopen = () => {
      term.writeln('\x1b[1;32mConnected to VM terminal!\x1b[0m')
    }

    socket.onerror = (error) => {
      term.writeln('\x1b[1;31mConnection error: Make sure the API is running and VM is reachable.\x1b[0m')
      console.error('WS Error:', error)
    }

    return () => {
      socket.close()
      term.dispose()
    }
  }, [ip])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-4xl overflow-hidden flex flex-col h-[600px]">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between bg-slate-800/50">
          <div className="flex items-center gap-2">
            <div className="flex gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-500/80" />
              <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <div className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <span className="text-xs font-medium text-slate-400 ml-2 uppercase tracking-wider font-mono">
              Root Console — {ip}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-100 transition-colors text-sm font-medium px-2 py-1 rounded hover:bg-slate-700"
          >
            Close
          </button>
        </div>
        <div className="flex-1 p-4 bg-[#0f172a]" ref={terminalRef} />
      </div>
    </div>
  )
}
