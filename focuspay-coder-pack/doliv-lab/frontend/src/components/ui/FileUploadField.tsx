import { UploadCloud } from 'lucide-react';
import type { Ref } from 'react';

interface FileUploadFieldProps {
  file: File | null;
  onChange: (file: File | null) => void;
  inputRef?: Ref<HTMLInputElement>;
  label?: string;
  hint?: string;
  requiredHint?: string;
}

export function FileUploadField({
  file,
  onChange,
  inputRef,
  label = 'Нажмите, чтобы прикрепить чек (фото или PDF)',
  hint,
  requiredHint,
}: FileUploadFieldProps) {
  return (
    <div>
      <label
        className={`relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed p-5 text-center text-sm hover:border-accent/50 ${
          file ? 'border-accent/50 bg-accent/5 text-white' : 'border-border bg-elevated/30 text-muted'
        }`}
      >
        <UploadCloud size={24} className="mb-2 text-accent" />
        <span className="relative z-0 px-2">{file ? file.name : label}</span>
        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf,.pdf,image/heic,image/heif,image/webp"
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          onChange={(e) => onChange(e.target.files?.[0] ?? null)}
        />
      </label>
      {!file && requiredHint && (
        <p className="mt-1 text-xs text-amber-400">{requiredHint}</p>
      )}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}
