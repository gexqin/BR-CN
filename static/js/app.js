// SPA 主控:hash 路由 + 状态轮询(普通 10s / 休息中 3s)
const App = {
  state: null,        // 最近一次 /api/game/state
  texts: null,
  pollTimer: null,
  routeToken: 0,      // 异步视图竞态防护
  pendingLog: '',     // 命令结果日志(渲染进 logbox 后清除)
  shownSense: 0,      // 已展示的感知日志最大 id(轮询增量追加)

  async boot() {
    try { this.texts = await API.get('/api/texts'); } catch (e) { /* 忽略 */ }
    window.addEventListener('hashchange', () => this.route());
    this.route();
  },

  async refreshState() {
    try {
      // 感知增量游标:服务端只返回 id 更大的感知,避免多标签页/刷新重复计数
      this.state = await API.get(`/api/game/state?since_id=${this.shownSense}`);
      if (this.state && this.state.view === 'main') {
        this.shownSense = Math.max(this.shownSense, this.state.sense_last || 0);
      }
      return this.state;
    } catch (e) {
      if (e.status === 401) { location.hash = '#/'; }
      return null;
    }
  },

  schedulePoll() {
    clearTimeout(this.pollTimer);
    if (!location.hash.startsWith('#/main')) return;
    const st = this.state;
    const interval = (st && (st.status === 'sleeping' || st.status === 'healing')) ? 3000 : 10000;
    this.pollTimer = setTimeout(async () => {
      if (location.hash !== '#/main') return;
      const s = await this.refreshState();
      if (!s) return;
      const box = document.getElementById('logbox');
      if (s.view !== 'main') {
        // 轮询期间死亡/优胜/逃生 → 整体重路由到对应视图
        clearTimeout(this.pollTimer);
        this.route();
        return;
      }
      // 增量追加新感知(服务端按 since_id 游标过滤,均为新条目)
      if (box && Array.isArray(s.senses)) {
        for (const sn of s.senses) {
          box.innerHTML = sn.html + '<hr>' + box.innerHTML;
        }
      }
      this.schedulePoll();
    }, interval);
  },

  async route() {
    clearTimeout(this.pollTimer);
    const token = ++this.routeToken;
    const root = document.getElementById('app');
    root.innerHTML = '';
    const h = location.hash || '#/';
    const page = h.slice(2).split('?')[0];
    // 首页整页背景(br_2k.png),其余页面纯黑
    document.body.classList.toggle('bg-home', page === '');
    try {
      if (page === '') { await Views.home(root); }
      else if (page === 'regist') { Views.regist(root); }
      else if (page === 'intro') {
        if (!(this.state && this.state.intro) && !(this.texts && this.texts.intro)) {
          location.hash = '#/main'; return;
        }
        Views.intro(root);
      }
      else if (page === 'map') { await Views.map(root); }
      else if (page === 'news') { await Views.news(root); }
      else if (page === 'rank') { await Views.rank(root); }
      else if (page === 'rule') { await Views.rule(root); }
      else if (page === 'admin') { await Views.admin(root); }
      else if (page === 'main' || page === 'ending') {
        const st = await this.refreshState();
        if (token !== this.routeToken) return;   // 期间已切换页面
        if (!st) { Views.home(root); return; }
        if (st.view === 'main') {
          Commands.mode = 'MAIN';
          Views.main(root, st, this.pendingLog);
          this.pendingLog = '';
          if (Commands.battle) Commands.renderBattle();
          else if (Commands.loot) Commands.renderLoot();
          this.schedulePoll();
        }
        else if (st.view === 'dead') { Views.dead(root, st); }
        else { Views.ending(root, st); }
      }
      else { Views.home(root); }
    } catch (e) {
      root.append(UI.el('p', { class: 'center msg-error' }, e.message));
    }
  },
};

App.boot();
