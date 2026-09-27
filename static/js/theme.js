document.addEventListener('DOMContentLoaded', () => {
  const root = document.body;
  const select = document.getElementById('themeSelect');
  if (!select) return;

  const savedTheme = localStorage.getItem('cems-theme') || 'blush';
  root.setAttribute('data-theme', savedTheme);
  select.value = savedTheme;

  select.addEventListener('change', (event) => {
    const theme = event.target.value;
    root.setAttribute('data-theme', theme);
    localStorage.setItem('cems-theme', theme);
  });
});
