// 组件工具
const UI = {
  el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v;
      else if (k === 'html') e.innerHTML = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const c of children) {
      if (c == null) continue;
      e.append(c.nodeType ? c : document.createTextNode(c));
    }
    return e;
  },
  panel(title, ...children) {
    const t = this.el('tr', {}, this.el('td', { colspan: '4', class: 'center' }, this.el('b', {}, title)));
    const rows = children.map(c => this.el('tr', {}, this.el('td', { colspan: '4' }, c)));
    return this.el('table', { class: 'panel', style: 'width:100%' }, t, ...rows);
  },
  row(label, value) {
    return this.el('tr', {},
      this.el('td', {}, this.el('b', {}, label)),
      this.el('td', { colspan: '3' }, value));
  },
  error(msg) {
    const box = document.getElementById('errmsg');
    // html 渲染:服务端消息(如死亡画面)含受控 HTML;玩家输入已在落库前转义
    if (box) { box.innerHTML = ''; box.append(this.el('span', { class: 'msg-error', html: msg })); }
  },
  // 游戏内模态弹窗(替代浏览器原生 confirm/alert,风格与整体一致)
  _modal(html, buttons) {
    return new Promise(resolve => {
      const done = (v) => { overlay.remove(); resolve(v); };
      const overlay = this.el('div', { class: 'modal-overlay' });
      overlay.addEventListener('click', e => { if (e.target === overlay) done(null); });
      const panel = this.el('div', { class: 'modal-panel' },
        this.el('div', { html }),
        this.el('div', { class: 'center', style: 'margin-top:14px' },
          ...buttons.map(([label, value], i) => this.el('button',
            { onclick: () => done(value) }, label))));
      overlay.append(panel);
      document.body.append(overlay);
      const btns = panel.querySelectorAll('button');
      if (btns.length) btns[0].focus();
    });
  },
  confirm(html) {
    return this._modal(html, [['确定', true], ['取消', false]])
      .then(v => v === true);
  },
  alert(html) {
    return this._modal(html, [['确定', true]]);
  },
  clearError() { const box = document.getElementById('errmsg'); if (box) box.innerHTML = ''; },
};
