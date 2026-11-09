import { ReactNode } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}

export function Modal({ open, onClose, title, children, wide }: ModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/45" onClick={onClose} />
      <div
        className={`relative border border-[#3f3f46] rounded-2xl shadow-2xl w-full ${wide ? 'max-w-2xl' : 'max-w-md'} max-h-[90vh] overflow-y-auto`}
        style={{ backgroundColor: '#1c1c22' }}
      >
        <div
          className="flex items-center justify-between px-5 py-4 border-b border-[#3f3f46] sticky top-0"
          style={{ backgroundColor: '#1c1c22' }}
        >
          <h3 className="font-semibold text-[#fafafa] text-lg">{title}</h3>
          <button onClick={onClose} className="text-[#a1a1aa] hover:text-white p-1" type="button" aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
        <div className="p-5 text-[#fafafa]">{children}</div>
      </div>
    </div>
  );
}
