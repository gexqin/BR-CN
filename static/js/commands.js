// 命令区:菜单状态机(对等原版 lib2.cgi COMMAND)
// 每个动作 POST /api/game/command 后整体重渲染主视图
const Commands = {
  mode: 'MAIN',
  battle: null,     // {target_id, target_name} 战斗菜单状态(P4)
  loot: null,       // {target_id, slots} 搜刮菜单状态(P4)

  reset() { this.mode = 'MAIN'; this.battle = null; this.loot = null; },

  // 耐力耗尽预判:本次操作的(最坏)消耗 ≥ 当前耐力 → drain 扣体力上限,先弹窗确认。
  // 消耗档位与后端 _spend_sta_move/_spend_sta_search/应急治疗/验毒一致(足伤>田径部)。
  async checkStaDrain(cmd) {
    const p = App.state && App.state.player;
    if (!p || p.sta == null) return true;
    const foot = (p.injuries || '').includes('足');
    const track = p.club === '田径部';
    let cost;   // 最坏消耗(后端判定 sta-cost <= 0 即倒下)
    if (cmd === 'move') cost = foot ? 17 : track ? 9 : 12;
    else if (cmd === 'explore') cost = foot ? 27 : track ? 17 : 22;
    else if (cmd === 'first_aid') cost = 70;
    else if (cmd === 'check_poison') cost = 30;
    else return true;
    if (p.sta > cost) return true;
    return UI.confirm(
      `当前耐力 <b>${p.sta}</b>,此操作将消耗约 <b>${cost}</b>。<br>` +
      '耐力耗尽会当场倒下,<b style="color:#e33">扣除体力上限</b>(严重时死亡)!<br><br>仍要继续吗?');
  },

  async run(cmd, args = {}) {
    UI.clearError();
    if (!await this.checkStaDrain(cmd)) return null;
    try {
      const res = await API.post('/api/game/command', { cmd, args });
      // 命令结果日志交给 App.pendingLog 由主视图渲染:直接 innerHTML 写入
      // logbox 会被随后的整体重渲染冲掉(表现为"按了没效果")
      const out = (res.inbox || '') + (res.log || '');
      if (out) App.pendingLog = out;
      this.reset();
      if (res.view === 'battle' && res.extras.battle) this.battle = res.extras.battle;
      if (res.view === 'loot' && res.extras.loot) this.loot = res.extras.loot;
      App.state = res.state;
      await App.route();
      if (res.view === 'radar') Views.radarModal(res.extras.radar);
      return res;
    } catch (e) {
      UI.error(e.message);
      return null;
    }
  },

  renderBattle() {
    const b = this.battle;
    if (!b) return;
    const area = document.getElementById('cmdarea');
    if (!area) return;
    area.innerHTML = '';
    const dengon = UI.el('input', { type: 'text', size: '24', maxlength: '64', placeholder: '留言' });
    area.append(UI.el('b', {}, `ＶＳ ${b.target.name}(${b.target.class_name} ${b.target.sex}${b.target.class_no}号)`),
      UI.el('div', { style: 'margin:6px 0' }, '留言:', dengon));
    for (const [mode, prof] of b.options) {
      area.append(UI.el('div', {},
        UI.el('button', {
          onclick: () => this.run('attack', {
            target_id: b.target.id, dengon: dengon.value.trim(),
          }),
        }, `${mode}(${Math.floor(prof / 20)})`)));
    }
    area.append(UI.el('div', { style: 'margin-top:6px' },
      UI.el('button', { onclick: () => this.run('attack', { run: true }) }, '逃亡')));
  },

  renderLoot() {
    const l = this.loot;
    if (!l) return;
    const area = document.getElementById('cmdarea');
    if (!area) return;
    area.innerHTML = '';
    area.append(UI.el('b', {}, `要夺取什么?(${l.target.name})`), UI.el('div', {}, '　'));
    for (const s of l.slots) {
      const btn = UI.el('button', { style: 'display:block;margin:2px 0' },
        `${s.name}/${s.eff}/${s.uses == null ? '∞' : s.uses}`);
      btn.addEventListener('click', () => this.run('loot', { target_id: l.target.id, slot: String(s.slot) }));
      area.append(btn);
    }
    area.append(UI.el('div', { style: 'margin-top:6px' },
      UI.el('button', { onclick: () => { this.loot = null; App.route(); } }, '离开')));
  },

  menu(items) {
    const area = document.getElementById('cmdarea');
    if (!area) return;
    area.innerHTML = '';
    for (const [label, fn, checked] of items) {
      const btn = UI.el('button', { style: 'display:block;margin:3px 0;width:95%' }, label);
      btn.addEventListener('click', fn);
      area.append(btn);
    }
  },

  render(st) {
    const p = st.player;
    if (this.mode === 'MAIN') {
      const items = [['移动', () => { this.mode = 'MOVE'; this.render(st); }]];
      if (st.place.index !== 0 || st.forbidden.hacked) {
        items.push(['探索', () => this.run('explore')]);
      }
      items.push(['物品', () => { this.mode = 'ITMAIN'; this.render(st); }]);
      if (st.place.index !== 0) {
        items.push(['治疗', () => this.run('heal')]);
        items.push(['睡眠', () => this.run('sleep')]);
      } else {
        // 分校恒不可休息(对等原版):按钮保留但操作无效,仅提示
        const noRest = () => UI.error('分校不能休息。');
        items.push(['治疗', noRest]);
        items.push(['睡眠', noRest]);
      }
      items.push(['特殊', () => { this.mode = 'SPECIAL'; this.render(st); }]);
      this.menu(items);
    } else if (this.mode === 'MOVE') {
      const area = document.getElementById('cmdarea');
      area.innerHTML = '';
      const sel = UI.el('select', { style: 'width:95%' },
        UI.el('option', { value: '' }, '— 去哪里呢? —'));
      for (let i = 0; i < 22; i++) {
        if (i === st.place.index) continue;
        const fb = st.forbidden.names;
        const tag = fb.includes(PLACES[i]) ? '【禁】' : '';
        sel.append(UI.el('option', { value: i }, `${tag}${PLACES[i]}(${COORDS[i]})`));
      }
      area.append(sel, UI.el('div', { style: 'margin:6px 0' },
        UI.el('button', { onclick: () => { if (sel.value !== '') this.run('move', { to: +sel.value }); } }, '确定'),
        ' ', UI.el('button', { onclick: () => { this.mode = 'MAIN'; this.render(st); } }, '返回')));
    } else if (this.mode === 'ITMAIN') {
      this.menu([
        ['物品使用/装备', () => { this.mode = 'ITEM'; this.render(st); }],
        ['物品丢弃', () => { this.mode = 'DEL'; this.render(st); }],
        ['物品整理', () => { this.mode = 'SEIRI'; this.render(st); }],
        ['物品合成', () => { this.mode = 'GOUSEI'; this.render(st); }],
        ...(p.weapon.name !== '空手' ? [
          ['装备武器解除', () => this.run('unequip_weapon')],
          ['装备武器丢弃', () => this.run('drop_weapon')]] : []),
        ['返回', () => { this.mode = 'MAIN'; this.render(st); }],
      ]);
    } else if (this.mode === 'ITEM' || this.mode === 'DEL') {
      const del = this.mode === 'DEL';
      const items = [['返回', () => { this.mode = 'ITMAIN'; this.render(st); }]];
      p.items.slice(0, 5).forEach((it, i) => {
        if (!it) return;
        const u = it.uses == null ? '∞' : it.uses;
        items.push([`${it.name}/${it.eff}/${u}`, () =>
          this.run(del ? 'drop_item' : 'use_item', { slot: i })]);
      });
      this.menu(items);
    } else if (this.mode === 'SEIRI' || this.mode === 'GOUSEI') {
      const area = document.getElementById('cmdarea');
      area.innerHTML = '';
      const isSort = this.mode === 'SEIRI';
      const mk = () => UI.el('select', {},
        UI.el('option', { value: '-1' }, '— 选择 —'),
        ...p.items.slice(0, 5).map((it, i) => it
          ? UI.el('option', { value: i }, `${it.name}/${it.eff}/${it.uses == null ? '∞' : it.uses}`)
          : null).filter(Boolean));
      const a = mk(), b = mk();
      area.append(a, ' × ', b, UI.el('div', { style: 'margin:6px 0' },
        UI.el('button', {
          onclick: () => {
            if (a.value === '-1' || b.value === '-1') return;
            this.run(isSort ? 'sort_pack' : 'craft', { a: +a.value, b: +b.value });
          },
        }, '确定'),
        ' ', UI.el('button', { onclick: () => { this.mode = 'ITMAIN'; this.render(st); } }, '返回')));
    } else if (this.mode === 'SPECIAL') {
      const items = [
        ['装备确认', () => { this.equipInfo(st); }],
        ['口头禅变更', () => { this.msgForm(st); }],
        ['熟练等级确认', () => { this.profInfo(st); }],
      ];
      if (p.injuries.length) {
        items.push(['应急治疗', () => { this.mode = 'OUKYU'; this.render(st); }]);
      }
      if (p.club === '料理研究部') {
        items.push(['验毒', () => { this.mode = 'PSCHECK'; this.render(st); }]);
      }
      if (p.items.slice(0, 5).some(i => i && i.name === '毒药')) {
        items.push(['投毒', () => { this.mode = 'POISON'; this.render(st); }]);
      }
      if (p.items.slice(0, 5).some(i => i && i.name === '携带式扩音器')) {
        items.push(['扩音器使用', () => { this.speakerForm(); }]);
      }
      if (p.items.slice(0, 5).some(i => i && i.name === '笔记本电脑' && (i.uses || 0) >= 1)) {
        items.push(['黑客入侵', () => this.run('hack')]);
      }
      items.push(['返回', () => { this.mode = 'MAIN'; this.render(st); }]);
      this.menu(items);
    } else if (this.mode === 'OUKYU') {
      const items = [['返回', () => { this.mode = 'SPECIAL'; this.render(st); }]];
      for (const part of p.injuries) {
        items.push([`治疗 ${part}`, () => this.run('first_aid', { part })]);
      }
      this.menu(items);
    } else if (this.mode === 'POISON' || this.mode === 'PSCHECK') {
      const ps = this.mode === 'PSCHECK';
      const items = [['返回', () => { this.mode = 'SPECIAL'; this.render(st); }]];
      p.items.slice(0, 5).forEach((it, i) => {
        // 仅食物类编码(与后端 poison/check_poison 校验一致)
        if (it && /SH|HH|SD|HD/.test(it.code)) {
          items.push([`${it.name}/${it.eff}/${it.uses == null ? '∞' : it.uses}`,
            () => this.run(ps ? 'check_poison' : 'poison', { slot: i })]);
        }
      });
      this.menu(items);
    } else {
      this.menu([['返回', () => { this.mode = 'MAIN'; this.render(st); }]]);
    }
  },

  equipInfo(st) {
    const p = st.player;
    const u = (x) => x == null ? '∞' : x;
    const area = document.getElementById('cmdarea');
    area.innerHTML = `<b>现在装备着的防具</b><br><br>
武：${p.weapon.name}/${u(p.weapon.uses)}<br>
体：${p.body_armor.name}/${u(p.body_armor.uses)}<br>
头：${p.head_armor ? p.head_armor.name + '/' + u(p.head_armor.uses) : '无'}<br>
腕：${p.arm_armor ? p.arm_armor.name + '/' + u(p.arm_armor.uses) : '无'}<br>
足：${p.foot_armor ? p.foot_armor.name + '/' + u(p.foot_armor.uses) : '无'}<br>
饰：${p.accessory ? p.accessory.name + '/' + u(p.accessory.uses) : '无'}<br><br>`;
    area.append(UI.el('button', { onclick: () => App.route() }, '返回'));
  },

  profInfo(st) {
    const p = st.player;
    const lv = (v) => Math.floor(v / 20);
    const area = document.getElementById('cmdarea');
    area.innerHTML = `<b>现在的熟练度等级</b><br><br>所属社团：${p.club}<br><br>
射：${lv(p.profs.wa)}(${p.profs.wa}) 棍：${lv(p.profs.wb)}(${p.profs.wb})<br>
投：${lv(p.profs.wc)}(${p.profs.wc}) 爆：${lv(p.profs.wd)}(${p.profs.wd})<br>
枪：${lv(p.profs.wg)}(${p.profs.wg}) 刺：${lv(p.profs.ws)}(${p.profs.ws})<br>
斩：${lv(p.profs.wn)}(${p.profs.wn}) 殴：${lv(p.profs.wp)}(${p.profs.wp})<br><br>`;
    area.append(UI.el('button', { onclick: () => App.route() }, '返回'));
  },

  msgForm(st) {
    const area = document.getElementById('cmdarea');
    area.innerHTML = '';
    const p = st.player;
    const mk = (label, val) => {
      const inp = UI.el('input', { type: 'text', size: '24', maxlength: '32', value: val || '' });
      return UI.el('div', { style: 'margin:4px 0' }, `${label}:`, inp);
    };
    const msg = mk('杀害时', p.msg || ''), dmes = mk('遗言', p.dmes || ''), com = mk('座右铭', p.com || '');
    area.append(UI.el('b', {}, '口头禅变更(最多32个汉字)'), msg, dmes, com,
      UI.el('div', { style: 'margin:6px 0' },
        UI.el('button', {
          onclick: () => this.run('change_msg',
            { msg: msg.querySelector('input').value, dmes: dmes.querySelector('input').value, com: com.querySelector('input').value }),
        }, '确定'),
        ' ', UI.el('button', { onclick: () => App.route() }, '返回')));
  },

  speakerForm() {
    const area = document.getElementById('cmdarea');
    area.innerHTML = '';
    const inp = UI.el('input', { type: 'text', size: '24', maxlength: '50' });
    area.append(UI.el('b', {}, '使用携带式扩音器(20个汉字以内)'), UI.el('div', {}, inp),
      UI.el('div', { style: 'margin:6px 0' },
        UI.el('button', { onclick: () => { if (inp.value.trim()) this.run('megaphone', { speech: inp.value.trim() }); } }, '播音'),
        ' ', UI.el('button', { onclick: () => App.route() }, '停止')));
  },
};

const PLACES = ['分校', '北之岬', '北村住宅街', '北村公所', '邮局', '消防署', '观音堂', '清水池', '西村神社', '旅馆废墟',
  '山岳地带', '隧道', '西村住宅街', '寺庙', '废弃学校', '南村神社', '森林地带', '源二郎池', '南村住宅街', '诊疗所',
  '灯塔', '南之岬'];
const COORDS = ['D-6', 'A-2', 'B-4', 'C-3', 'C-4', 'C-5', 'C-6', 'D-3', 'E-2', 'E-4',
  'E-5', 'E-7', 'F-2', 'F-9', 'G-3', 'G-6', 'H-4', 'H-6', 'I-6', 'I-7', 'I-10', 'J-6'];
