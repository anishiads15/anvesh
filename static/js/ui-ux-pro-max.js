/**
 * UI/UX Pro Max Design System & Interaction Engine
 * AICTE SENTRIX Inter-Bureau Grievance Monitoring Platform
 * 
 * Features imported from ui-ux-pro-max design intelligence:
 * 1. Dark / Light / System Theme Engine with localStorage persistence
 * 2. Accent Color Palette Switcher (Blue, Emerald, Indigo, Amber, Rose)
 * 3. UI Density Switcher (Comfortable vs Compact Auditor View)
 * 4. Border Radius Customizer (Sharp, Modern, Pill)
 * 5. High-Contrast Accessibility Mode (WCAG AAA)
 * 6. Global Keyboard Shortcuts (/ to search, Ctrl+J for dark mode, Ctrl+Shift+D for design drawer)
 * 7. Copy-to-clipboard for Grievance IDs and USNs
 * 8. Live Client-side Table FilterBar and Instant Search
 */

(function () {
  'use strict';

  // --- 1. THEME & TOKEN ENGINE ---
  const STORAGE_KEY_THEME = 'sentrix_theme';
  const STORAGE_KEY_ACCENT = 'sentrix_accent';
  const STORAGE_KEY_DENSITY = 'sentrix_density';
  const STORAGE_KEY_RADIUS = 'sentrix_radius';
  const STORAGE_KEY_CONTRAST = 'sentrix_contrast';

  function getStoredSetting(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function setStoredSetting(key, val) {
    try {
      localStorage.setItem(key, val);
    } catch (e) {}
  }

  // Apply initial theme immediately to prevent FOUC (Flash of Unstyled Content)
  function initTheme() {
    const savedTheme = getStoredSetting(STORAGE_KEY_THEME, 'light');
    const savedAccent = getStoredSetting(STORAGE_KEY_ACCENT, 'blue');
    const savedDensity = getStoredSetting(STORAGE_KEY_DENSITY, 'comfortable');
    const savedRadius = getStoredSetting(STORAGE_KEY_RADIUS, '18');
    const savedContrast = getStoredSetting(STORAGE_KEY_CONTRAST, 'standard');

    applyTheme(savedTheme, false);
    applyAccent(savedAccent, false);
    applyDensity(savedDensity, false);
    applyRadius(savedRadius, false);
    applyContrast(savedContrast, false);
  }

  function applyTheme(theme, save = true) {
    const html = document.documentElement;
    let effectiveTheme = theme;
    if (theme === 'system') {
      effectiveTheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    html.setAttribute('data-theme', effectiveTheme);
    if (save) setStoredSetting(STORAGE_KEY_THEME, theme);

    // Update Dark Mode Toggle icon in header
    const toggleBtn = document.getElementById('uupmThemeToggleBtn');
    if (toggleBtn) {
      if (effectiveTheme === 'dark') {
        toggleBtn.innerHTML = '<i class="bi bi-sun-fill text-warning"></i>';
        toggleBtn.setAttribute('title', 'Switch to Light Mode (Ctrl+J)');
        toggleBtn.setAttribute('aria-label', 'Switch to Light Mode');
      } else {
        toggleBtn.innerHTML = '<i class="bi bi-moon-stars-fill text-secondary"></i>';
        toggleBtn.setAttribute('title', 'Switch to Dark Mode (Ctrl+J)');
        toggleBtn.setAttribute('aria-label', 'Switch to Dark Mode');
      }
    }

    // Update active state in Design Drawer radio pills
    document.querySelectorAll('[data-theme-choice]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-theme-choice') === theme);
    });

    // Notify any charts to refresh colors if Chart.js is present
    if (window.Chart && window.Chart.instances) {
      Object.values(window.Chart.instances).forEach(chart => {
        try {
          if (chart.options && chart.options.scales) {
            const gridColor = effectiveTheme === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
            const textColor = effectiveTheme === 'dark' ? '#94a3b8' : '#64748b';
            if (chart.options.scales.x) {
              chart.options.scales.x.grid = chart.options.scales.x.grid || {};
              chart.options.scales.x.grid.color = gridColor;
              chart.options.scales.x.ticks = chart.options.scales.x.ticks || {};
              chart.options.scales.x.ticks.color = textColor;
            }
            if (chart.options.scales.y) {
              chart.options.scales.y.grid = chart.options.scales.y.grid || {};
              chart.options.scales.y.grid.color = gridColor;
              chart.options.scales.y.ticks = chart.options.scales.y.ticks || {};
              chart.options.scales.y.ticks.color = textColor;
            }
            chart.update();
          }
        } catch (e) {}
      });
    }
  }

  function applyAccent(accent, save = true) {
    document.documentElement.setAttribute('data-accent', accent);
    if (save) setStoredSetting(STORAGE_KEY_ACCENT, accent);
    document.querySelectorAll('[data-accent-choice]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-accent-choice') === accent);
    });
  }

  function applyDensity(density, save = true) {
    document.documentElement.setAttribute('data-density', density);
    if (save) setStoredSetting(STORAGE_KEY_DENSITY, density);
    document.querySelectorAll('[data-density-choice]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-density-choice') === density);
    });
  }

  function applyRadius(radius, save = true) {
    document.documentElement.style.setProperty('--card-radius', radius + 'px');
    if (save) setStoredSetting(STORAGE_KEY_RADIUS, radius);
    document.querySelectorAll('[data-radius-choice]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-radius-choice') === radius);
    });
  }

  function applyContrast(contrast, save = true) {
    document.documentElement.setAttribute('data-contrast', contrast);
    if (save) setStoredSetting(STORAGE_KEY_CONTRAST, contrast);
    document.querySelectorAll('[data-contrast-choice]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-contrast-choice') === contrast);
    });
  }

  // --- 2. GLOBAL SHORTCUTS & INTERACTION ---
  function initKeyboardShortcuts() {
    document.addEventListener('keydown', function (e) {
      // Ignore if user is inside an input, textarea, or contenteditable
      const target = e.target;
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;

      // '/' to focus search bar
      if (e.key === '/' && !isInput) {
        e.preventDefault();
        const searchInput = document.querySelector('.header-search input') || document.querySelector('input[name="search"]');
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
      }

      // 'Ctrl+J' or 'Cmd+J' to toggle dark/light mode
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') {
        e.preventDefault();
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
        applyTheme(currentTheme === 'dark' ? 'light' : 'dark', true);
      }

      // 'Ctrl+Shift+D' to toggle design drawer
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault();
        const drawerEl = document.getElementById('uupmDesignDrawer');
        if (drawerEl && window.bootstrap) {
          const bsDrawer = bootstrap.Offcanvas.getInstance(drawerEl) || new bootstrap.Offcanvas(drawerEl);
          bsDrawer.toggle();
        }
      }
    });
  }

  // --- 3. COPY TO CLIPBOARD ENHANCER ---
  function initCopyButtons() {
    document.addEventListener('click', function (e) {
      const copyBtn = e.target.closest('[data-copy-text]');
      if (!copyBtn) return;

      const text = copyBtn.getAttribute('data-copy-text');
      if (!text) return;

      navigator.clipboard.writeText(text).then(() => {
        const origHtml = copyBtn.innerHTML;
        copyBtn.innerHTML = '<i class="bi bi-check-lg text-success me-1"></i>Copied!';
        copyBtn.classList.add('btn-success-subtle');
        setTimeout(() => {
          copyBtn.innerHTML = origHtml;
          copyBtn.classList.remove('btn-success-subtle');
        }, 1800);
      }).catch(() => {
        // Fallback for older browsers
        const temp = document.createElement('textarea');
        temp.value = text;
        document.body.appendChild(temp);
        temp.select();
        document.execCommand('copy');
        document.body.removeChild(temp);
        copyBtn.classList.add('btn-success-subtle');
        setTimeout(() => copyBtn.classList.remove('btn-success-subtle'), 1800);
      });
    });
  }

  // --- 4. INSTANT CLIENT-SIDE FILTER BAR ---
  function initClientSideFilterBars() {
    const filterInput = document.querySelector('[data-table-search]');
    if (!filterInput) return;

    const targetTable = document.querySelector(filterInput.getAttribute('data-table-search'));
    if (!targetTable) return;

    filterInput.addEventListener('input', function () {
      const query = this.value.toLowerCase().trim();
      const rows = targetTable.querySelectorAll('tbody tr');
      let visibleCount = 0;

      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        const match = !query || text.includes(query);
        row.style.display = match ? '' : 'none';
        if (match) visibleCount++;
      });

      const countBadge = document.querySelector('[data-table-count]');
      if (countBadge) {
        countBadge.textContent = visibleCount;
      }
    });
  }

  // --- 5. INITIALIZE ON DOM READY ---
  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    initKeyboardShortcuts();
    initCopyButtons();
    initClientSideFilterBars();

    // Listen to system theme change if 'system' selected
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
        if (getStoredSetting(STORAGE_KEY_THEME, 'light') === 'system') {
          applyTheme('system', false);
        }
      });
    }

    // Attach click listeners to Design Drawer interactive buttons
    document.querySelectorAll('[data-theme-choice]').forEach(btn => {
      btn.addEventListener('click', function () {
        applyTheme(this.getAttribute('data-theme-choice'), true);
      });
    });

    document.querySelectorAll('[data-accent-choice]').forEach(btn => {
      btn.addEventListener('click', function () {
        applyAccent(this.getAttribute('data-accent-choice'), true);
      });
    });

    document.querySelectorAll('[data-density-choice]').forEach(btn => {
      btn.addEventListener('click', function () {
        applyDensity(this.getAttribute('data-density-choice'), true);
      });
    });

    document.querySelectorAll('[data-radius-choice]').forEach(btn => {
      btn.addEventListener('click', function () {
        applyRadius(this.getAttribute('data-radius-choice'), true);
      });
    });

    document.querySelectorAll('[data-contrast-choice]').forEach(btn => {
      btn.addEventListener('click', function () {
        applyContrast(this.getAttribute('data-contrast-choice'), true);
      });
    });

    // Dark Mode quick toggle button
    const quickToggle = document.getElementById('uupmThemeToggleBtn');
    if (quickToggle) {
      quickToggle.addEventListener('click', function () {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        applyTheme(current === 'dark' ? 'light' : 'dark', true);
      });
    }
  });

  // Expose API globally for inline controls
  window.SentrixUI = {
    setTheme: applyTheme,
    setAccent: applyAccent,
    setDensity: applyDensity,
    setRadius: applyRadius,
    setContrast: applyContrast,
    showToast: function (title, message, type = 'info') {
      const toastContainer = document.getElementById('uupmToastContainer');
      if (!toastContainer) return;
      const toastEl = document.createElement('div');
      toastEl.className = `toast align-items-center text-bg-${type === 'error' ? 'danger' : type} border-0 show shadow-lg mb-2`;
      toastEl.setAttribute('role', 'alert');
      toastEl.setAttribute('aria-live', 'assertive');
      toastEl.setAttribute('aria-atomic', 'true');
      toastEl.innerHTML = `
        <div class="d-flex">
          <div class="toast-body">
            <strong>${title}</strong><div class="small">${message}</div>
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      `;
      toastContainer.appendChild(toastEl);
      setTimeout(() => {
        toastEl.classList.remove('show');
        setTimeout(() => toastEl.remove(), 400);
      }, 4000);
    }
  };

  // Run immediate theme setup before complete DOM render to avoid flash
  initTheme();
})();
