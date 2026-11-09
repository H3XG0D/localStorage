-- Fixed admin weekly salary (replaces admin_payroll_roles % shares)

UPDATE app_settings
SET value = value || '{"admin_weekly_salary_rub": 7000}'::jsonb,
    updated_at = now()
WHERE key = 'business'
  AND NOT (value ? 'admin_weekly_salary_rub');
