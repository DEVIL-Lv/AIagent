import axios from 'axios';

const api = axios.create({
  baseURL: '/api', // Use proxy
  timeout: 300000, // 5 minutes for local whisper
});

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
  search: (query: string) => {
    const formData = new FormData();
    formData.append('query', query);
    return api.post('/knowledge/search', formData);
  }
};

export default api;
