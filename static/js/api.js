// fetch 封装:cookie 凭据、统一错误(detail 兼容 dict/字符串/422 数组)
const API = {
  async request(method, url, body) {
    const opt = { method, headers: {}, credentials: 'same-origin' };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(url, opt);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const detail = (await res.json()).detail;
        if (typeof detail === 'string') msg = detail;
        else if (detail && typeof detail.message === 'string') msg = detail.message;
        else if (Array.isArray(detail) && detail[0]) {
          const d = detail[0];
          msg = (d.msg || '输入错误') + (d.loc ? `(${d.loc.join('.')})` : '');
        }
      } catch (e) { /* 非 JSON 响应,保留状态码 */ }
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return res.json();
  },
  get(url) { return this.request('GET', url); },
  post(url, body) { return this.request('POST', url, body); },
};
