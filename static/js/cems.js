/* ============================================
    CEMS Global JavaScript
    ============================================ */

document.addEventListener('DOMContentLoaded', function() {
  // ===== App Shell Mobile Hamburger Toggle =====
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const appSidebar = document.getElementById('app-sidebar');
  const sidebarScrim = document.getElementById('sidebar-scrim');

  if (sidebarToggle && appSidebar && sidebarScrim) {
    sidebarToggle.addEventListener('click', function() {
      if (window.innerWidth > 1024) {
        const collapsed = document.body.classList.toggle('sidebar-collapsed');
        sidebarToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        return;
      }
      const isOpen = appSidebar.classList.toggle('open');
      sidebarScrim.classList.toggle('active', isOpen);
      sidebarToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      document.body.style.overflow = isOpen ? 'hidden' : '';
    });

    sidebarScrim.addEventListener('click', function() {
      appSidebar.classList.remove('open');
      sidebarScrim.classList.remove('active');
      sidebarToggle.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    });

    // Close sidebar on escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && appSidebar.classList.contains('open')) {
        appSidebar.classList.remove('open');
        sidebarScrim.classList.remove('active');
        sidebarToggle.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      }
    });
  }

  // Auto-dismiss flash messages
  const flashMessages = document.querySelectorAll('.cems-alert');
  flashMessages.forEach(alert => {
    setTimeout(() => {
      alert.style.opacity = '0';
      alert.style.transform = 'translateX(100%)';
      alert.style.transition = 'all 0.3s ease';
      setTimeout(() => alert.remove(), 300);
    }, 5000);
  });

  // Close sidebar on window resize (desktop)
  window.addEventListener('resize', () => {
    if (window.innerWidth > 1024 && appSidebar && sidebarScrim) {
      document.body.style.overflow = '';
      appSidebar.classList.remove('open');
      sidebarScrim.classList.remove('active');
    }
  });

  // data-confirm dialogs are handled once, globally, in ext-modules.js

  // Search box focus effect
  const searchBox = document.querySelector('.cems-search-box input');
  if (searchBox) {
    searchBox.addEventListener('focus', () => {
      searchBox.parentElement.classList.add('focused');
    });
    searchBox.addEventListener('blur', () => {
      searchBox.parentElement.classList.remove('focused');
    });
  }

  // Table row click for action links
  const tableRows = document.querySelectorAll('.cems-table tbody tr');
  tableRows.forEach(row => {
    const actionLink = row.querySelector('.cems-table-actions a:first-child');
    if (actionLink) {
      row.style.cursor = 'pointer';
      row.addEventListener('click', (e) => {
        if (!e.target.closest('button') && !e.target.closest('form')) {
          window.location.href = actionLink.href;
        }
      });
    }
  });

  // Lightbox for gallery
  const galleryItems = document.querySelectorAll('.cems-gallery-item');
  const lightbox = document.getElementById('cems-lightbox');
  const lightboxImg = document.getElementById('cems-lightbox-img');
  const lightboxClose = document.getElementById('cems-lightbox-close');

  galleryItems.forEach(item => {
    item.addEventListener('click', () => {
      const img = item.querySelector('img');
      if (img && lightbox && lightboxImg) {
        lightboxImg.src = img.src;
        lightbox.classList.add('active');
      }
    });
  });

  if (lightboxClose && lightbox) {
    lightboxClose.addEventListener('click', () => {
      lightbox.classList.remove('active');
    });

    lightbox.addEventListener('click', (e) => {
      if (e.target === lightbox) {
        lightbox.classList.remove('active');
      }
    });
  }

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Escape to close modals/lightbox
    if (e.key === 'Escape') {
      if (lightbox) lightbox.classList.remove('active');
      const modal = document.querySelector('.cems-modal-backdrop.active');
      if (modal) modal.classList.remove('active');
    }

    // Ctrl+K or / to focus search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      const searchInput = document.querySelector('.cems-search-box input');
      if (searchInput) searchInput.focus();
    }
  });

  // Global image fallback: replace broken images with placeholder SVG
  const placeholderUrl = '/static/images/placeholder.svg';
  document.addEventListener('error', function(e) {
    if (e.target.tagName === 'IMG' && e.target.src && !e.target.dataset.fallbackApplied) {
      e.target.dataset.fallbackApplied = 'true';
      e.target.src = placeholderUrl;
    }
  }, true);

  // Fallback for images that haven't fired error yet (lazy-loaded or cached 404)
  const allImgs = document.querySelectorAll('img[src]:not([onerror])');
  allImgs.forEach(img => {
    img.onerror = function() {
      this.onerror = null;
      this.src = placeholderUrl;
    };
  });

  // ===== Camera Scan Toggle (checkin page) =====
  const scanBtn = document.getElementById('cems-scan-btn');
  const scanInterface = document.getElementById('cems-scan-interface');
  const scanForm = document.getElementById('cems-scan-form');
  const scanArea = document.getElementById('cems-scan-area');

  if (scanBtn && scanInterface && scanForm) {
    scanBtn.addEventListener('click', () => {
      scanInterface.classList.add('active');
      scanForm.style.display = 'none';
    });
  }

  if (scanArea) {
    document.addEventListener('click', function(e) {
      if (scanArea.classList.contains('scanning') &&
          !scanArea.contains(e.target) &&
          !e.target.closest('#cems-scan-interface')) {
        scanArea.classList.remove('scanning');
      }
    });
  }
});
