import axios from 'axios';

const api = axios.create({
  baseURL: '/api', // Use proxy
  timeout: 300000, // 5 minutes for local whisper
});

type StreamCallbacks = {
  onToken: (token: string) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
};

const streamPost = async (path: string, payload: any, callbacks: StreamCallbacks) => {
  const base = api.defaults.baseURL || '';
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => '');
    const message = text || `HTTP ${res.status}`;
    callbacks.onError?.(message);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  let reading = true;
  while (reading) {
    const { value, done } = await reader.read();
    if (done) {
      reading = false;
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r/g, '');

    let parsing = true;
    while (parsing) {
      const boundaryIndex = buffer.indexOf('\n\n');
      if (boundaryIndex < 0) {
        parsing = false;
        break;
      }
      const chunk = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);

      const lines = chunk.split('\n');
      let event = 'message';
      let data = '';
      for (const line of lines) {
        if (line.startsWith('event:')) {
          event = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          data += line.slice(5).trim();
        }
      }
      if (!data) {
        continue;
      }
      if (data === '[DONE]' || event === 'done') {
        callbacks.onDone?.();
        return;
      }
      if (event === 'error') {
        callbacks.onError?.(data);
        return;
      }
      try {
        const parsed = JSON.parse(data);
        if (parsed?.token !== undefined) {
          callbacks.onToken(String(parsed.token));
        } else if (parsed?.message !== undefined) {
          callbacks.onToken(String(parsed.message));
        } else {
          callbacks.onToken(data);
        }
      } catch {
        callbacks.onToken(data);
      }
    }
  }

  callbacks.onDone?.();
};

const normalizeCustomer = (data: any) => {
  if (!data || typeof data !== 'object') return data;
  const mapped = { ...data };
  if (mapped.stage === undefined && data['阶段'] !== undefined) mapped.stage = data['阶段'];
  if (mapped.risk_profile === undefined && data['风险偏好'] !== undefined) mapped.risk_profile = data['风险偏好'];
  if (mapped.summary === undefined && data['画像摘要'] !== undefined) mapped.summary = data['画像摘要'];
  return mapped;
};

const normalizeCustomerList = (data: any) => {
  if (!Array.isArray(data)) return data;
  return data.map((item) => normalizeCustomer(item));
};

const normalizeReplySuggestion = (data: any) => {
  if (!data || typeof data !== 'object') return data;
  const mapped = { ...data };
  if (mapped.suggested_reply === undefined && data['建议回复'] !== undefined) mapped.suggested_reply = data['建议回复'];
  if (mapped.rationale === undefined && data['回复理由'] !== undefined) mapped.rationale = data['回复理由'];
  if (mapped.rationale === undefined && data['理由'] !== undefined) mapped.rationale = data['理由'];
  if (mapped.risk_alert === undefined && data['风险提示'] !== undefined) mapped.risk_alert = data['风险提示'];
  return mapped;
};

const normalizeProgression = (data: any) => {
  if (!data || typeof data !== 'object') return data;
  const mapped = { ...data };
  if (mapped.recommendation === undefined && data['推进建议'] !== undefined) mapped.recommendation = data['推进建议'];
  if (mapped.reason === undefined && data['核心理由'] !== undefined) mapped.reason = data['核心理由'];
  if (mapped.key_blockers === undefined && data['关键阻碍'] !== undefined) mapped.key_blockers = data['关键阻碍'];
  if (mapped.next_step_suggestion === undefined && data['下一步建议'] !== undefined) mapped.next_step_suggestion = data['下一步建议'];
  return mapped;
};

export const customerApi = {
  getCustomers: () => api.get('/customers/').then((res) => ({ ...res, data: normalizeCustomerList(res.data) })),
  getCustomer: (id: number) => api.get(`/customers/${id}`).then((res) => ({ ...res, data: normalizeCustomer(res.data) })),
  createCustomer: (data: any) => {
    const formData = new FormData();
    formData.append('name', data.name);
    if (data.bio) formData.append('bio', data.bio);
    if (data.file) formData.append('file', data.file);
    
    return api.post('/customers/', formData).then((res) => ({ ...res, data: normalizeCustomer(res.data) }));
  },
  deleteCustomer: (id: number) => api.delete(`/customers/${id}`),
  updateCustomer: (id: number, data: any) => api.put(`/customers/${id}`, data).then((res) => ({ ...res, data: normalizeCustomer(res.data) })),
  addCustomerData: (id: number, data: any) => api.post(`/customers/${id}/data/`, data),
  generateSummary: (id: number) => api.post(`/customers/${id}/generate-summary`).then((res) => ({ ...res, data: normalizeCustomer(res.data) })),
  uploadAudio: (id: number, formData: FormData) => api.post(`/customers/${id}/upload-audio`, formData),
  uploadDocument: (id: number, formData: FormData) => api.post(`/customers/${id}/upload-document`, formData),
  uploadAudioGlobal: (formData: FormData) => api.post(`/chat/global/upload-audio`, formData),
  uploadDocumentGlobal: (formData: FormData) => api.post(`/chat/global/upload-document`, formData),
  deleteData: (customerId: number, dataId: number) => api.delete(`/customers/${customerId}/data/${dataId}`),
  runSkill: (id: number, skillName: string, question?: string, model?: string) => api.post(`/customers/${id}/run-skill`, {
    skill_name: skillName,
    question,
    model
  }),
  chat: (id: number, message: string, model?: string) => api.post(`/customers/${id}/chat`, { message, model }),
  agentChat: (id: number, query: string, history: any[], model?: string) => api.post(`/customers/${id}/agent-chat`, { query, history, model }),
  chatGlobal: (message: string, model?: string) => api.post(`/chat/global`, { message, model }),
  chatGlobalUploadImage: (formData: FormData) => api.post(`/chat/global/upload-image`, formData),
  chatStream: (id: number, message: string, model: string | undefined, callbacks: StreamCallbacks) =>
    streamPost(`/customers/${id}/chat/stream`, { message, model }, callbacks),
  agentChatStream: (id: number, query: string, history: any[], model: string | undefined, callbacks: StreamCallbacks) =>
    streamPost(`/customers/${id}/agent-chat/stream`, { query, history, model }, callbacks),
  chatGlobalStream: (message: string, model: string | undefined, callbacks: StreamCallbacks) =>
    streamPost(`/chat/global/stream`, { message, model }, callbacks),
};

export const llmApi = {
  getConfigs: () => api.get('/admin/llm-configs/'),
  createConfig: (data: any) => api.post('/admin/llm-configs/', data),
  updateConfig: (id: number, data: any) => api.put(`/admin/llm-configs/${id}`, data),
  deleteConfig: (id: number) => api.delete(`/admin/llm-configs/${id}`),
};

export const analysisApi = {
  getStats: () => api.get('/analysis/stats'),
  suggestReply: (customerId: number, intent?: string, chatContext?: string) => 
    api.post('/analysis/suggest-reply', { 
        customer_id: customerId, 
        intent, 
        chat_context: chatContext 
    }).then((res) => ({ ...res, data: normalizeReplySuggestion(res.data) })),
  evaluateProgression: (customerId: number) => 
    api.post('/analysis/evaluate-progression', { 
        customer_id: customerId 
    }).then((res) => ({ ...res, data: normalizeProgression(res.data) })),
};

export const scriptApi = {
  getScripts: () => api.get('/scripts/'),
  uploadScript: (formData: FormData) => api.post('/scripts/upload', formData),
  updateScript: (id: number, formData: FormData) => api.put(`/scripts/${id}`, formData),
  deleteScript: (id: number) => api.delete(`/scripts/${id}`),
  importFeishu: (payload: {
    spreadsheet_token: string;
    range_name?: string;
    import_type?: string;
    table_id?: string;
    data_source_id?: number;
    category?: string;
    title_field?: string | null;
    content_fields?: string[];
    use_ai_processing?: boolean;
  }) => api.post('/scripts/import-feishu', payload),
  simulate: (scriptId: number, query: string) => {
    const formData = new FormData();
    formData.append('script_id', scriptId.toString());
    formData.append('query', query);
    return api.post('/scripts/simulate', formData);
  }
};

export const dataSourceApi = {
  importFromExcel: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/admin/import-excel', formData);
  },
  getExcelHeaders: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/admin/import-excel/headers', formData);
  },
  getConfigs: () => api.get('/admin/data-sources/'),
  createConfig: (data: any) => api.post('/admin/data-sources/', data),
  updateConfig: (id: number, data: any) => api.put(`/admin/data-sources/${id}`, data),
  deleteConfig: (id: number) => api.delete(`/admin/data-sources/${id}`),
  importFeishu: (token: string, range: string, type: string = "sheet", tableId: string = "", dataSourceId?: number) => 
    api.post('/admin/import-feishu', { 
        spreadsheet_token: token, 
        range_name: range,
        import_type: type,
        table_id: tableId,
        data_source_id: dataSourceId
    }),
  getFeishuHeaders: (token: string, range: string, type: string = "sheet", tableId: string = "", dataSourceId?: number) =>
    api.post('/admin/feishu/headers', {
        spreadsheet_token: token,
        range_name: range,
        import_type: type,
        table_id: tableId,
        data_source_id: dataSourceId
    }),
};

export const routingApi = {
  getRules: () => api.get('/admin/routing-rules/'),
  createRule: (data: any) => api.post('/admin/routing-rules/', data),
  deleteRule: (id: number) => api.delete(`/admin/routing-rules/${id}`),
  getMappings: () => api.get('/admin/skill-routes/'),
  updateMapping: (skillName: string, llmConfigId: number) => api.post('/admin/skill-routes/', { skill_name: skillName, llm_config_id: llmConfigId }),
};

export const knowledgeApi = {
  list: () => api.get('/knowledge/'),
  get: (id: number) => api.get(`/knowledge/${id}`),
  add: (formData: FormData) => api.post('/knowledge/', formData),
  update: (id: number, formData: FormData) => api.put(`/knowledge/${id}`, formData),
  delete: (id: number) => api.delete(`/knowledge/${id}`),
  importFeishu: (payload: {
    spreadsheet_token: string;
    range_name?: string;
    import_type?: string;
    table_id?: string;
    data_source_id?: number;
    category?: string;
    title_field?: string | null;
    content_fields?: string[];
    use_ai_processing?: boolean;
  }) => api.post('/knowledge/import-feishu', payload),
  search: (query: string) => {
    const formData = new FormData();
    formData.append('query', query);
    return api.post('/knowledge/search', formData);
  }
};

export default api;
