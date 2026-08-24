// 视图渲染:登录/注册/剧情/主界面/地图/新闻/排行/结局/管理
// 文案与布局对等原版;命令区随游戏状态切换(P3 起接入命令提交)
const Views = {
  // ---- 首页/登录 ----
  async home(root) {
    root.append(
      UI.el('h1', { class: 'center red title' }, '■ BATTLE ROYALE ■(V02.00)'),
      UI.el('p', { class: 'center', html: '西历20XX年,大东亚共和国。<br><br>「新世纪恐怖主义对策特别法」——通称「BR法」。<br>每年从全国的中学校3年级中随机选出一个班级,<br>并将他们送到无人岛等地,让他们自相残杀,直到剩下最后一人为止——<br>这就是这个国家最疯狂的「游戏」。' }),
      UI.el('div', { id: 'errmsg', class: 'center' }),
    );
    // 会话仍有效(7 天 cookie)则免登录,直接给继续游戏入口
    let who = null;
    try { who = await API.get('/api/auth/whoami'); } catch (e) { /* 未登录 */ }
    if (who && who.player) {
      root.append(
        UI.el('p', { class: 'center big' },
          `欢迎回来,${who.player.f_name} ${who.player.l_name}。`),
        UI.el('p', { class: 'center', style: 'margin:12px 0' },
          UI.el('a', { href: '#/main', class: 'red big' }, '>> 继续游戏 <<')));
    } else {
      root.append(UI.el('form', { class: 'center', onsubmit: async (e) => {
        e.preventDefault();
        UI.clearError();
        const f = e.target;
        try {
          const res = await API.post('/api/auth/login', {
            username: f.Id.value.trim(), password: f.Password.value });
          if (res.dead) {
            // 死亡角色:弹窗展示死亡信息,确认后进入死亡画面
            await UI.alert(res.message);
          }
          location.hash = '#/main';
        } catch (err) { UI.error(err.message); }
      } },
        UI.el('div', {}, 'ID:', UI.el('input', { name: 'Id', size: '10', maxlength: '8' }),
          '　密码:', UI.el('input', { name: 'Password', type: 'password', size: '10', maxlength: '32' })),
        UI.el('div', { style: 'margin-top:6px' }, UI.el('input', { type: 'submit', value: '实行' })),
      ));
    }
    root.append(UI.el('p', { class: 'center' },
      UI.el('a', { href: '#/rule', class: 'red' }, '游戏说明'), ' / ',
      UI.el('a', { href: '#/regist', class: 'red' }, '新学员注册'), ' / ',
      UI.el('a', { href: '#/rank', class: 'red' }, '生存者一览'), ' / ',
      UI.el('a', { href: '#/news', class: 'red' }, '进行状况'), ' / ',
      UI.el('a', { href: '#/map', class: 'red' }, '会场地图'), ' / ',
      UI.el('a', { href: '#/admin', class: 'red' }, 'ADMIN')),
    );
  },

  // ---- 注册 ----
  regist(root) {
    const fields = [
      ['F_Name', '姓', '（姓名请使用汉字填写,不超过 4 字。）'],
      ['L_Name', '名', ''],
      ['Sex', '性別', ''],
      ['Id', 'ID', '（ID为半角英数字8文字以内,密码为半角英数字32文字以内）'],
      ['Password', '密码', ''],
      ['Message', '口癖', '（杀害对手时所说的台词,最多32个汉字。）'],
      ['Message2', '遺言', '（自己死亡时的台词。）'],
      ['Comment', '个人座右铭', '（可以在生存者一览里看到。）'],
    ];
    const form = UI.el('form', { onsubmit: async (e) => {
      e.preventDefault(); UI.clearError();
      const f = e.target;
      try {
        const res = await API.post('/api/auth/register', {
          username: f.Id.value.trim(), password: f.Password.value,
          f_name: f.F_Name.value.trim(), l_name: f.L_Name.value.trim(),
          sex: f.Sex.value, msg: f.Message.value.trim(),
          dmes: f.Message2.value.trim(), com: f.Comment.value.trim(),
        });
        App.state = App.state || {}; App.state.intro = res.intro;
        location.hash = '#/intro';
      } catch (err) { UI.error(err.message); }
    } });
    for (const [name, label, note] of fields) {
      if (name === 'Sex') {
        form.append(UI.el('div', {}, '性別:',
          UI.el('select', { name },
            UI.el('option', { value: '', selected: '' }, '- 性別 -'),
            UI.el('option', { value: '男生' }, '男生'),
            UI.el('option', { value: '女生' }, '女生'))));
      } else {
        const type = name === 'Password' ? 'password' : 'text';
        // ID 上限 8(与后端一致),其余文本 32
        const ml = name === 'Id' ? '8' : '32';
        form.append(UI.el('div', { style: 'margin:3px 0' },
          `${label}：`, UI.el('input', { name, type, size: '30', maxlength: ml })));
      }
      if (note) form.append(UI.el('div', { class: 'center', style: 'font-size:12px' }, note));
    }
    form.append(UI.el('div', { style: 'margin-top:8px' },
      UI.el('input', { type: 'submit', value: '确定' }), '　',
      UI.el('input', { type: 'reset', value: '清除' })));
    root.append(
      UI.el('h2', { class: 'center red title' }, '转学手续'),
      UI.el('p', { class: 'center' }, '你是新来的转校生吗?请在申请表上填写好你的姓名和性别,然后按确定提交入学申请。'),
      UI.el('div', { id: 'errmsg', class: 'center' }),
      UI.el('div', { class: 'center' }, form),
      UI.el('p', { class: 'center' }, UI.el('a', { href: '#/', class: 'red big' }, '返回')),
    );
  },

  // ---- 开场剧情 ----
  intro(root) {
    const intro = (App.state && App.state.intro) ||
      (App.texts && App.texts.intro) || '';
    root.append(
      UI.el('h2', { class: 'center red title' }, '登记完成'),
      UI.el('div', { class: 'center', html: intro }),
      UI.el('div', { class: 'center', style: 'margin:16px' },
        UI.el('button', { onclick: () => { location.hash = '#/main'; } }, '走出教室')),
    );
  },

  // ---- 主界面 ----
  main(root, st, prependLog) {
    if (!st) { location.hash = '#/'; return; }
    const p = st.player;
    const injuries = p.injuries.length ? p.injuries.join('　') : '　';
    const itemHtml = p.items.slice(0, 5).filter(Boolean)
      .map(i => `${i.name}/${i.eff}/${i.uses == null ? '∞' : i.uses}`).join('<br>') || '　';
    root.append(UI.el('div', { id: 'errmsg', class: 'center' }));
    root.append(UI.el('p', { class: 'center' },
      UI.el('span', { class: 'place-name' },
        `${st.place.name}(${st.place.coord})`)));
    root.append(UI.el('div', { class: 'navbar center' },
      '>>', UI.el('a', { href: '#/', class: 'red' }, '首页'), ' ',
      '>>', UI.el('a', { href: '#/rule', class: 'red' }, '说明'), ' ',
      '>>', UI.el('a', { href: '#/rank', class: 'red' }, '成员'), ' ',
      '>>', UI.el('a', { href: '#/map', class: 'red' }, '地图'), ' ',
      '>>', UI.el('a', { href: '#/news', class: 'red' }, '新闻'), ' ',
      '>>', UI.el('a', { href: '#', class: 'red', onclick: async (e) => {
        e.preventDefault();
        try { await API.post('/api/auth/logout'); } catch (err) { /* 忽略 */ }
        location.hash = '#/';
      } }, '登出')));
    const info = UI.el('table', { class: 'panel' },
      UI.el('tr', {}, UI.el('td', { colspan: 4, class: 'center' }, UI.el('b', {}, '参加者信息'))),
      UI.row('名字', `${p.f_name} ${p.l_name}`),
      UI.row('学 号', `${p.class_name} ${p.sex}${p.class_no}号`),
      UI.row('所属社团', p.club || ''),
      UI.row('负伤部位', injuries),
      UI.el('tr', {}, UI.el('td', {}, UI.el('b', {}, '等级')), UI.el('td', {}, String(p.level)),
        UI.el('td', {}, UI.el('b', {}, '经验值')), UI.el('td', {}, `${p.exp}/${p.next_exp}`)),
      UI.el('tr', {}, UI.el('td', {}, UI.el('b', {}, '体力')), UI.el('td', {}, `${p.hit}/${p.mhit}`),
        UI.el('td', {}, UI.el('b', {}, '耐力')), UI.el('td', {}, `${p.sta}/${p.maxsta}`)),
      UI.el('tr', {}, UI.el('td', {}, UI.el('b', {}, '攻击力')), UI.el('td', {}, `${p.att}+${p.wep_att}`),
        UI.el('td', {}, UI.el('b', {}, '武器')), UI.el('td', {}, `${p.weapon.name}/${p.weapon.uses == null ? '∞' : p.weapon.uses}`)),
      UI.el('tr', {}, UI.el('td', {}, UI.el('b', {}, '防御力')), UI.el('td', {}, `${p.deff}+${p.armor_total}`),
        UI.el('td', {}, UI.el('b', {}, '防具')), UI.el('td', {}, `${p.body_armor.name}/${p.body_armor.uses == null ? '∞' : p.body_armor.uses}`)),
      UI.el('tr', {}, UI.el('td', { colspan: 4, class: 'center' }, UI.el('b', {}, '所持物品'))),
      UI.el('tr', {}, UI.el('td', { colspan: 4, html: itemHtml })));
    const cmd = UI.el('div', { id: 'cmdbox', class: 'panel main-cmd', style: 'padding:8px;border:1px solid #fff' },
      UI.el('b', {}, '选择项目'), UI.el('div', { id: 'cmdarea', style: 'margin-top:6px' }, '加载中……'));
    // 双栏布局(窄屏自动堆叠);日志区整宽在下
    const layout = UI.el('div', { class: 'main-layout' },
      UI.el('div', { class: 'main-info' }, info),
      cmd);
    root.append(layout,
      UI.el('div', { class: 'panel log-stream', id: 'logbox',
        html: (prependLog || '') + (st.log || '') }));
    if (typeof Commands !== 'undefined') Commands.render(st);   // P3 接入
    if (st.place.is_forbidden && !st.forbidden.hacked) {
      UI.error(`当前所在地 ${st.place.name} 是禁止地区!赶快离开!`);
    }
  },

  // ---- 地图 ----
  async map(root) {
    let m;
    try { m = await API.get('/api/map'); }
    catch (e) { root.append(UI.el('p', { class: 'center msg-error' }, e.message)); return; }
    const tbl = UI.el('table', { class: 'map-grid center' });
    tbl.append(UI.el('tr', {}, UI.el('th', {}), ...m.cols.map(c => UI.el('th', {}, c))));
    m.rows.forEach((r, ri) => {
      const cells = [UI.el('th', {}, r)];
      m.cols.forEach((c, ci) => {
        const cell = m.cells[`${r}${c}`];
        if (cell) {
          const cls = cell.state === 'forbidden' ? 'forbidden' : cell.state === 'next' ? 'next' : 'land';
          const title = cell.state === 'forbidden' ? '禁止地区' : cell.state === 'next' ? '下次禁止' : '';
          const td = UI.el('td', { class: cls, title });
          td.innerHTML = mapSVG(TERRAIN_SCENES[terrainOf(cell.name)]
            + coastStrips(m.cells, m.cols, m.rows, ci, ri))
            + `<span class="map-label">${cell.name}</span>`;
          cells.push(td);
        } else if (ISLAND_FILLER.has(`${r}-${parseInt(c)}`)) {
          // 岛上填充格(非地点):草地/灌木/疏林,与地点格连成整片陆地
          const td = UI.el('td', { class: 'land' });
          td.innerHTML = mapSVG(FILLER_SCENES[(ci * 7 + ri * 13) % FILLER_SCENES.length]
            + coastStrips(m.cells, m.cols, m.rows, ci, ri));
          cells.push(td);
        } else {
          const td = UI.el('td', { class: 'sea' });
          td.innerHTML = mapSVG(SEA_SCENES[(ri + ci) % 2]);
          cells.push(td);
        }
      });
      tbl.append(UI.el('tr', {}, ...cells));
    });
    // 地图页加宽版心(.map-page):11 列大格子需比默认 568px 更宽
    const wrap = UI.el('div', { class: 'map-page' },
      UI.el('h2', { class: 'center red' }, '会场地图'),
      UI.el('p', { class: 'center' },
        UI.el('span', { class: 'red' }, '红字'), '=现在禁止的地区　',
        UI.el('span', { class: 'yellow' }, '黄字'), '=下次禁止的地区'),
      tbl);
    root.append(wrap);
    // 原生 append(null) 会把 null 渲染成文字"null",必须条件追加
    if (m.hacked) {
      wrap.append(UI.el('p', { class: 'center lime' }, '禁止区域已被解除。'));
    }
    wrap.append(UI.el('p', { class: 'center', style: 'margin-top:10px' },
      Views.backLink()));
  },

  // 返回入口:已登录回游戏,未登录回首页
  backLink() {
    const inGame = !!(App.state && App.state.player);
    return UI.el('a', { href: inGame ? '#/main' : '#/', class: 'red big' },
      inGame ? '返回游戏' : '返回首页');
  },

  // ---- 新闻 ----
  async news(root) {
    let ns;
    try { ns = await API.get('/api/news'); }
    catch (e) { root.append(UI.el('p', { class: 'center msg-error' }, e.message)); return; }
    root.append(UI.el('h2', { class: 'center red' }, '进行状况'));
    let lastDate = '';
    for (const n of ns) {
      if (n.date !== lastDate) {
        root.append(UI.el('h3', { class: 'lime' }, `${n.date}`));
        lastDate = n.date;
      }
      const color = n.kind.startsWith('DEATH') || n.kind === 'DEATHAREA' ? 'red'
        : n.kind === 'ENTRY' ? 'yellow' : 'lime';
      root.append(UI.el('div', {}, UI.el('span', { class: color }, `(${n.time}) ${n.text}`)));
    }
    if (!ns.length) root.append(UI.el('p', { class: 'center' }, '暂无情报。'));
    root.append(UI.el('p', { class: 'center', style: 'margin-top:10px' },
      Views.backLink()));
  },

  // ---- 排行 ----
  async rank(root) {
    let rk;
    try { rk = await API.get('/api/rank'); }
    catch (e) { root.append(UI.el('p', { class: 'center msg-error' }, e.message)); return; }
    const tbl = UI.el('table', { class: 'panel center', style: 'width:100%' },
      UI.el('tr', {}, ...['姓名', '班级', '学号', '座右铭'].map(h => UI.el('th', {}, h))));
    for (const m of rk.members) {
      tbl.append(UI.el('tr', {},
        UI.el('td', {}, `${m.f_name} ${m.l_name}`),
        UI.el('td', {}, m.class_name),
        UI.el('td', {}, `${m.sex}${m.class_no}号`),
        UI.el('td', {}, m.com || '')));
    }
    root.append(
      UI.el('h2', { class: 'center red' }, '生存者一览'),
      tbl,
      UI.el('p', { class: 'center' }, `[剩余${rk.alive}人]`),
      UI.el('p', { class: 'center', style: 'margin-top:10px' }, Views.backLink()));
  },

  // ---- 规则 ----
  async rule(root) {
    try {
      const r = await API.get('/api/rule');
      const box = UI.el('div', { html: r.html });
      root.append(box);
    } catch (e) { root.append(UI.el('p', { class: 'msg-error' }, e.message)); }
    root.append(UI.el('p', { class: 'center', style: 'margin-top:10px' },
      Views.backLink()));
  },

  // ---- 雷达弹层 ----
  radarModal(radar) {
    const tbl = UI.el('table', { class: 'map-grid center' });
    tbl.append(UI.el('tr', {}, UI.el('th', {}), ...radar.cols.map(c => UI.el('th', {}, c))));
    for (const r of radar.rows) {
      const cells = [UI.el('th', {}, r)];
      for (const c of radar.cols) {
        const cell = radar.cells[`${r}${c}`];
        if (cell) {
          const num = cell.count > 0 ? String(cell.count) : '　';
          const cls = cell.mine && cell.count > 0 ? 'red' : (cell.forbidden ? 'yellow' : 'white');
          cells.push(UI.el('td', {},
            cell.forbidden ? UI.el('span', { class: 'red' }, '∵') : UI.el('span', { class: cls }, num)));
        } else {
          cells.push(UI.el('td', { class: 'sea' }, '　'));
        }
      }
      tbl.append(UI.el('tr', {}, ...cells));
    }
    const modal = UI.el('div', {
      style: 'position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9;display:flex;align-items:center;justify-content:center',
      onclick: (e) => { if (e.target === modal) modal.remove(); },
    }, UI.el('div', { class: 'panel', style: 'padding:16px;background:#000;max-width:96vw;overflow-x:auto' },
      UI.el('b', {}, '使用了雷达。'), tbl,
      UI.el('div', { class: 'center', style: 'font-size:12px;margin-top:6px' },
        '数字：区域内的人数 / 红色数字：自己所在区域 / ∵：禁止区域'),
      UI.el('div', { class: 'center', style: 'margin-top:8px' },
        UI.el('button', { onclick: () => modal.remove() }, '关闭'))));
    document.body.append(modal);
  },

  // ---- 死亡/结局 ----
  dead(root, data) {
    root.append(UI.el('div', { class: 'center', html: data.player.html }),
      UI.el('p', { class: 'center' }, UI.el('a', {
        href: '#/', class: 'red big', onclick: async (e) => {
          // 死亡会话没有保留价值:返回首页时直接登出,首页回到登录/注册入口
          e.preventDefault();
          try { await API.post('/api/auth/logout'); } catch (err) { /* 忽略 */ }
          // 只改 hash:hashchange 会触发路由;再手动 route() 会双次渲染导致首页重复
          location.hash = '#/';
        } }, '返回首页')));
  },
  ending(root, st) {
    const texts = App.texts || {};
    let html = '';
    if (st.view === 'ending_win') {
      html = `<h2 class="center red title">优胜者诞生</h2><div class="center">${texts.ending_win || ''}</div>`;
    } else {
      html = `<h2 class="center red title">程序紧急停止</h2><div class="center">${
        st.key_user ? (texts.ending_escape_keyuser || '') : (texts.ending_escape_others || '')}</div>`;
    }
    root.append(UI.el('div', { html }),
      UI.el('p', { class: 'center' }, UI.el('a', { href: '#/', class: 'red big' }, '返回首页')));
  },

  // ---- 管理 ----
  async admin(root) {
    root.append(UI.el('h2', { class: 'center red' }, '管理室'));
    root.append(UI.el('p', { class: 'center' },
      UI.el('a', { href: '#/', class: 'red' }, '返回首页')));
    const box = UI.el('div', { id: 'adminbox' });
    root.append(UI.el('div', { id: 'errmsg', class: 'center' }), box);
    // 管理会话仍有效(7 天 cookie)则直接进面板,刷新免重登
    try {
      const r = await API.get('/api/auth/whoami');
      if (r && r.admin) { await Views.adminPanel(box); return; }
    } catch (e) { /* 未登录,落回密码表单 */ }
    box.append(UI.el('form', { class: 'center', onsubmit: async (e) => {
      e.preventDefault(); UI.clearError();
      try {
        await API.post('/api/admin/login', { password: e.target.pw.value });
        await Views.adminPanel(box);
      } catch (err) { UI.error(err.message); }
    } },
      '管理密码:', UI.el('input', { name: 'pw', type: 'password' }),
      UI.el('input', { type: 'submit', value: '确定' })));
  },
  async adminPanel(box) {
    box.innerHTML = '';
    box.append(UI.el('p', { class: 'center lime' }, '管理员登录成功。'),
      UI.el('div', { class: 'center', style: 'margin:8px 0' },
        UI.el('button', { onclick: async () => {
          if (!await UI.confirm('确定执行数据初始化(开新局)?<br><br>'
            + '<span class="red">将清除旧局全部用户信息(不可恢复)</span>,并开启一局新游戏。')) return;
          try {
            const r = await API.post('/api/admin/new_game');
            await UI.alert(`新游戏 #${r.game_id} 已开始。`);
            location.reload();      // 管理会话保留,重载后直接回到面板
          } catch (err) { UI.error(err.message); }
        } }, '数据初始化(开新局)'),
        ' ', UI.el('button', { onclick: () => Views.adminList(box) }, '用户一览'),
        ' ', UI.el('button', { onclick: async () => {
          const r = await API.post('/api/admin/backup?label=web');
          box.prepend(UI.el('p', { class: 'center lime' }, `备份 #${r.backup_id} 完成。`));
        } }, '备份保存'),
        ' ', UI.el('button', { onclick: () => Views.adminBackups(box) }, '备份读取'),
        ' ', UI.el('button', { onclick: async () => {
          try { await API.post('/api/auth/logout'); } catch (e) { /* 忽略 */ }
          await App.route();          // 重建视图 → 回到密码表单
        } }, '退出'),
        ' ', UI.el('a', { href: '#/', class: 'red' }, '返回首页')));
    await Views.adminList(box);
  },
  async adminList(box) {
    try {
      const r = await API.get('/api/admin/players');
      const tbl = UI.el('table', { class: 'panel center', style: 'width:100%' },
        UI.el('tr', {}, ...['ID', '姓名', '班级', '状态', '杀', '地点', '操作'].map(h => UI.el('th', {}, h))));
      for (const p of r.players) {
        const statusHtml = p.status === 'dead'
          ? `<span class="red">${p.status}${p.death ? '(' + p.death + ')' : ''}</span>` : p.status;
        const act = UI.el('td', {});
        if (!['dead', 'won', 'escaped'].includes(p.status) && !p.npc) {
          const btn = UI.el('button', {}, '处刑');
          btn.addEventListener('click', async () => {
            const message = prompt('输入处刑留言(可空):') || '';
            try {
              await API.post('/api/admin/execute', { player_id: p.id, message });
              await Views.adminList(box);
            } catch (err) { UI.error(err.message); }
          });
          act.append(btn);
        }
        tbl.append(UI.el('tr', {},
          UI.el('td', {}, p.npc ? '—' : (p.username || '')),
          UI.el('td', {}, p.name + (p.npc ? '(NPC)' : '')),
          UI.el('td', {}, `${p.class_name} ${p.sex}${p.class_no}号`),
          UI.el('td', { html: statusHtml }),
          UI.el('td', {}, String(p.kill)),
          UI.el('td', {}, p.place),
          act));
      }
      const panel = document.getElementById('adminlist') || UI.el('div', { id: 'adminlist' });
      panel.innerHTML = '';
      const scroll = UI.el('div', { class: 'table-scroll' }, tbl);   // 窄屏横向滚动
      let header;
      if (r.game) {
        const st = r.game.status === 'running' ? '进行中'
          : r.game.status === 'finished_win' ? '已终局' : '已结束';
        header = `当前第 ${r.game.id} 轮(${st})　当前 ${r.players.length} 名角色。`;
      } else {
        header = '尚未开局。';
      }
      panel.append(UI.el('p', { class: 'center lime' }, header), scroll);
      const target = document.getElementById('adminbox');
      const existing = document.getElementById('adminlist');
      if (existing) existing.remove();
      target.append(panel);
    } catch (e) { UI.error(e.message); }
  },
  async adminBackups(box) {
    try {
      const r = await API.get('/api/admin/backups');
      let list = document.getElementById('adminbackups');
      if (!list) {
        list = UI.el('div', { id: 'adminbackups' });
        document.getElementById('adminbox').append(list);
      }
      list.innerHTML = '';
      list.append(UI.el('b', {}, '备份列表'));
      for (const b of r.backups) {
        const btn = UI.el('button', {}, `#${b.id} ${b.label || ''} 回滚`);
        btn.addEventListener('click', async () => {
          if (!confirm(`回滚到备份 #${b.id}?当前进度将丢失。`)) return;
          await API.post('/api/admin/rollback', { backup_id: b.id });
          alert('回滚完成。');
        });
        list.append(UI.el('div', {}, btn));
      }
    } catch (e) { UI.error(e.message); }
  },
};

// ---- 地图岛屿背景(inline SVG 58×46,按地点名称匹配地形) ----
const GRASS_SCENE = '<rect width="58" height="46" fill="#2f6b3a"/>'
  + '<path d="M12 30 q2 -5 4 0 M40 22 q2 -5 4 0 M28 36 q2 -5 4 0" stroke="#3f8a4f" fill="none"/>';
const TERRAIN_SCENES = {
  village: GRASS_SCENE
    + '<path d="M4 27 L12 19 L20 27 Z" fill="#7d5a3a"/><rect x="7" y="27" width="10" height="9" fill="#c9b28a"/>'
    + '<path d="M32 29 L40 22 L48 29 Z" fill="#7d5a3a"/><rect x="35" y="29" width="10" height="7" fill="#c9b28a"/>',
  office: GRASS_SCENE
    + '<rect x="12" y="10" width="34" height="26" fill="#98a2ac"/><rect x="12" y="10" width="34" height="4" fill="#6f7a84"/>'
    + '<rect x="16" y="18" width="5" height="5" fill="#dfe6ec"/><rect x="24" y="18" width="5" height="5" fill="#dfe6ec"/>'
    + '<rect x="32" y="18" width="5" height="5" fill="#dfe6ec"/><rect x="40" y="18" width="4" height="5" fill="#dfe6ec"/>'
    + '<rect x="16" y="27" width="5" height="5" fill="#dfe6ec"/><rect x="24" y="27" width="5" height="5" fill="#dfe6ec"/>'
    + '<rect x="32" y="27" width="5" height="5" fill="#dfe6ec"/>',
  school: GRASS_SCENE
    + '<rect x="10" y="16" width="38" height="20" fill="#c8b68f"/><path d="M7 16 L29 7 L51 16 Z" fill="#8a6f4d"/>'
    + '<rect x="15" y="22" width="6" height="6" fill="#6b5636"/><rect x="26" y="22" width="6" height="6" fill="#6b5636"/>'
    + '<rect x="37" y="22" width="6" height="6" fill="#6b5636"/><rect x="26" y="30" width="6" height="6" fill="#4a3421"/>',
  temple: GRASS_SCENE
    + '<rect x="17" y="25" width="24" height="13" fill="#a06a3a"/><path d="M12 25 L29 15 L46 25 Z" fill="#6d4426"/>'
    + '<rect x="25" y="29" width="8" height="9" fill="#4a2d17"/>',
  shrine: GRASS_SCENE
    + '<rect x="15" y="13" width="4" height="25" fill="#c0392b"/><rect x="39" y="13" width="4" height="25" fill="#c0392b"/>'
    + '<rect x="11" y="11" width="36" height="4" fill="#e74c3c"/><rect x="15" y="19" width="28" height="3" fill="#a93226"/>',
  pond: GRASS_SCENE
    + '<ellipse cx="29" cy="24" rx="20" ry="11" fill="#2e86c1"/>'
    + '<path d="M18 22 q4 -3 9 0 M30 27 q4 -3 9 0" stroke="#85c1e9" fill="none" stroke-width="1.5"/>',
  mountain: GRASS_SCENE
    + '<path d="M6 38 L21 13 L36 38 Z" fill="#7d7468"/><path d="M21 13 L26 21 L16 21 Z" fill="#eceff1"/>'
    + '<path d="M30 38 L41 20 L52 38 Z" fill="#8d8478"/>',
  forest: GRASS_SCENE
    + '<path d="M1 32 L7 11 L13 32 Z" fill="#1c4a2a"/><path d="M23 28 L29 6 L35 28 Z" fill="#1c4a2a"/>'
    + '<path d="M45 32 L51 12 L57 32 Z" fill="#1c4a2a"/>'
    + '<path d="M12 24 L18 10 L24 24 Z" fill="#256b39"/><path d="M9 38 L18 20 L27 38 Z" fill="#256b39"/>'
    + '<rect x="16.5" y="38" width="3" height="7" fill="#5d4037"/>'
    + '<path d="M36 22 L42 8 L48 22 Z" fill="#1e5631"/><path d="M33 36 L42 18 L51 36 Z" fill="#1e5631"/>'
    + '<rect x="40.5" y="36" width="3" height="8" fill="#5d4037"/>'
    + '<path d="M26 40 L30 30 L34 40 Z" fill="#2f7a45"/><rect x="28.5" y="40" width="3" height="5" fill="#5d4037"/>',
  ruin: GRASS_SCENE
    + '<rect x="9" y="20" width="16" height="18" fill="#8d8d8d"/><path d="M9 20 L25 13 L25 20 Z" fill="#6e6e6e"/>'
    + '<rect x="31" y="26" width="16" height="12" fill="#7a7a7a"/><path d="M31 26 L37 21 L43 24 L47 26 Z" fill="#666666"/>'
    + '<rect x="13" y="25" width="4" height="5" fill="#3a3a3a"/>',
  tunnel: GRASS_SCENE
    + '<path d="M2 46 L13 14 L29 8 L45 14 L56 46 Z" fill="#6b7a5a"/>'      /* 山体 */
    + '<path d="M13 14 L29 8 L45 14 L38 18 L29 15 L20 18 Z" fill="#7f9069"/>' /* 山顶亮面 */
    + '<path d="M2 46 L13 26 L20 46 Z" fill="#5d6b4e"/><path d="M56 46 L45 26 L38 46 Z" fill="#5d6b4e"/>' /* 两坡阴影 */
    + '<path d="M19 46 L19 31 Q29 21 39 31 L39 46 Z" fill="#8d959c"/>'      /* 混凝土洞门 */
    + '<path d="M22 46 L22 32 Q29 25 36 32 L36 46 Z" fill="#0d0d0d"/>',     /* 黑洞口 */
  clinic: GRASS_SCENE
    + '<rect x="13" y="15" width="32" height="21" fill="#e8ebee"/><path d="M11 15 L29 9 L47 15 Z" fill="#b0b7bd"/>'
    + '<rect x="26" y="17" width="6" height="3" fill="#e74c3c"/><rect x="27.5" y="15.5" width="3" height="6" fill="#e74c3c"/>'
    + '<rect x="18" y="25" width="8" height="11" fill="#9aa2a8"/><rect x="34" y="25" width="6" height="6" fill="#cfd6dc"/>',
  lighthouse: GRASS_SCENE
    + '<path d="M24 40 L27.5 14 L30.5 14 L34 40 Z" fill="#eceff1"/>'
    + '<path d="M25 30 L33 30 L33.6 34 L24.4 34 Z" fill="#e74c3c"/><path d="M26.4 22 L32.6 22 L33.2 26 L25.8 26 Z" fill="#e74c3c"/>'
    + '<rect x="26" y="9" width="6" height="5" fill="#f9e79f"/><path d="M32 11 L44 7 L44 12 Z" fill="#f7dc6f" opacity=".7"/>',
  grass: GRASS_SCENE,
};
const SEA_SCENES = [
  '<rect width="58" height="46" fill="#164a8a"/>'
    + '<path d="M8 14 q4 -4 8 0 q4 4 8 0" stroke="#3f74c0" fill="none" stroke-width="1.5"/>'
    + '<path d="M32 30 q4 -4 8 0" stroke="#2b5da6" fill="none" stroke-width="1.5"/>',
  '<rect width="58" height="46" fill="#164a8a"/>'
    + '<path d="M30 10 q4 -4 8 0 q4 4 8 0" stroke="#3f74c0" fill="none" stroke-width="1.5"/>'
    + '<path d="M10 32 q4 -4 8 0" stroke="#2b5da6" fill="none" stroke-width="1.5"/>',
];
function terrainOf(name) {
  if (name.includes('岬')) return 'mountain';   /* 岬=海边山地 */
  if (name.includes('住宅街')) return 'village';
  if (name.includes('池')) return 'pond';
  if (name.includes('山岳')) return 'mountain';
  if (name.includes('森林')) return 'forest';
  if (name.includes('神社')) return 'shrine';
  if (name.includes('观音堂') || name.includes('寺庙')) return 'temple';
  if (name.includes('灯塔')) return 'lighthouse';
  if (name.includes('隧道')) return 'tunnel';
  if (name.includes('废')) return 'ruin';
  if (name.includes('诊疗所')) return 'clinic';
  if (name.includes('学校') || name.includes('分校')) return 'school';
  if (name.includes('公所') || name.includes('邮局') || name.includes('消防署')) return 'office';
  return 'grass';
}
function mapSVG(scene) {
  return `<svg class="map-bg" viewBox="0 0 58 46" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">${scene}</svg>`;
}

// ---- 岛屿轮廓:显式陆地清单 ----
// 22 个可达地点之外,这些格子(用户指定)也是陆地,连成整片岛身;其余为海。
const ISLAND_FILLER = new Set(['B-2', 'C-2', 'D-2', 'B-3', 'B-5',
  'D-4', 'D-5', 'E-3', 'E-6', 'F-3', 'F-4', 'F-5', 'F-6', 'F-7', 'F-8', 'G-4',
  'G-5', 'G-7', 'G-8', 'G-9', 'H-5', 'H-7', 'H-8', 'H-9', 'I-5']);
function isLandCell(cellsMap, cols, rows, ci, ri) {
  if (ci < 0 || ci >= cols.length || ri < 0 || ri >= rows.length) return false;
  // 地点格键为"行+补零列"(如 "D06",与服务端一致);填充格键为"行-列"(如 "D-6")
  if (cellsMap && cellsMap[`${rows[ri]}${cols[ci]}`]) return true;
  return ISLAND_FILLER.has(`${rows[ri]}-${parseInt(cols[ci])}`);
}
// 陆地格朝海一侧画沙滩条,拼出整条海岸线
function coastStrips(cellsMap, cols, rows, ci, ri) {
  const W = 2.5, s = [];
  if (!isLandCell(cellsMap, cols, rows, ci, ri - 1)) s.push(`<rect width="58" height="${W}" fill="#d9c27e"/>`);
  if (!isLandCell(cellsMap, cols, rows, ci, ri + 1)) s.push(`<rect y="${46 - W}" width="58" height="${W}" fill="#d9c27e"/>`);
  if (!isLandCell(cellsMap, cols, rows, ci - 1, ri)) s.push(`<rect width="${W}" height="46" fill="#d9c27e"/>`);
  if (!isLandCell(cellsMap, cols, rows, ci + 1, ri)) s.push(`<rect x="${58 - W}" width="${W}" height="46" fill="#d9c27e"/>`);
  return s.join('');
}
// 岛上非地点格的填充景观(草地/灌木/疏林)
const FILLER_SCENES = [
  GRASS_SCENE,
  GRASS_SCENE + '<ellipse cx="18" cy="24" rx="8" ry="5" fill="#3f8a4f"/>'
    + '<ellipse cx="40" cy="15" rx="6" ry="4" fill="#357a44"/>',
  GRASS_SCENE + '<path d="M14 34 L19 22 L24 34 Z" fill="#1e5631"/>'
    + '<path d="M34 30 L40 18 L46 30 Z" fill="#256b39"/>',
];
