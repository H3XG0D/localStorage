/** Map common API error strings to Russian for mobile UX. */
export function translateApiError(message: string): string {
  const m = message.trim();
  const lower = m.toLowerCase();
  if (lower.includes('invalid file type') || lower.includes('неподдерживаемый формат')) {
    return 'Неподдерживаемый формат. Прикрепите JPG, PNG, PDF или сделайте скриншот чека.';
  }
  if (lower.includes('file too large') || lower.includes('слишком большой')) {
    return m.includes('МБ') || m.includes('MB') ? m : 'Файл слишком большой. Уменьшите фото или сожмите PDF.';
  }
  if (lower.includes('doliv amount must equal') || lower.includes('required amount')) {
    return 'Сумма должна точно совпадать с суммой заявки.';
  }
  if (lower.includes('rate must be between')) {
    return 'Курс должен быть от 50 до 200.';
  }
  if (lower.includes('not assigned to you')) {
    return 'Эта заявка назначена другому доливщику.';
  }
  if (lower.includes('request not available') || lower.includes('not in progress')) {
    return 'Заявка уже недоступна. Обновите страницу.';
  }
  if (lower.includes('could not validate credentials')) {
    return 'Сессия истекла. Войдите снова.';
  }
  return m;
}
