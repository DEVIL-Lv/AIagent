import React, { useEffect, useState, useRef } from 'react';
import { 
  Layout, Typography, Tag, Button, Input, message, Spin, Avatar, 
  List, Modal, Upload, Empty, Tooltip, Badge, Dropdown, Menu, Card, Select, Popconfirm, Checkbox, Table
} from 'antd';
import { 
  UserOutlined, RobotOutlined, SendOutlined, PlusOutlined, 
  UploadOutlined, FileTextOutlined, SafetyCertificateOutlined,
  RiseOutlined, SearchOutlined, MoreOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined,
  CheckCircleFilled, ClockCircleFilled, CloseCircleFilled,
  PaperClipOutlined, EllipsisOutlined, DeleteOutlined, DatabaseOutlined, EditOutlined, SaveOutlined,
  ArrowLeftOutlined, ReloadOutlined, AudioOutlined, LoadingOutlined, BulbOutlined
} from '@ant-design/icons';
import { customerApi, dataSourceApi, llmApi, analysisApi } from '../services/api';
import ChatMessageList, { ChatMessage } from '../components/ChatMessageList';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;
const { Option } = Select;

interface Customer {
  id: number;
  name: string;
  stage: string;
  summary: string;
  risk_profile: string;
  contact_info: string;
  created_at: string;
}

const GLOBAL_CHAT_STORAGE_KEY = 'aiagent.globalChatHistory.v1';
const DEFAULT_GLOBAL_CHAT_HISTORY: ChatMessage[] = [
  { role: 'ai', content: '您好！我是全局 AI 助手。您可以问我通用的销售技巧，或者让我帮您撰写邮件、分析话术。', timestamp: new Date().toISOString() }
];

const toSafeUploadFilename = (name: string) => {
  const lastDot = name.lastIndexOf('.');
  const ext = lastDot >= 0 ? name.slice(lastDot) : '';
  const base = lastDot >= 0 ? name.slice(0, lastDot) : name;
  const safeBase = base.replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'file';
  const safeExt = ext.replace(/[^\w.]+/g, '');
  return `${safeBase}${safeExt}`;
};

const getErrorDetail = (error: any) => {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  return null;
};

const Dashboard: React.FC = () => {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [filteredCustomers, setFilteredCustomers] = useState<Customer[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [displayFields, setDisplayFields] = useState<string[] | null>(null);
  
  // Chat State
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]); // Now User <-> Agent Chat
  const [customerLogs, setCustomerLogs] = useState<ChatMessage[]>([]); // Historical Customer Data
  const [globalChatHistory, setGlobalChatHistory] = useState<ChatMessage[]>(() => {
    try {
      if (typeof window === 'undefined') return DEFAULT_GLOBAL_CHAT_HISTORY;
      const raw = window.localStorage.getItem(GLOBAL_CHAT_STORAGE_KEY);
      if (!raw) return DEFAULT_GLOBAL_CHAT_HISTORY;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return DEFAULT_GLOBAL_CHAT_HISTORY;
      const normalized: ChatMessage[] = parsed
        .filter((m: any) => m && (m.role === 'user' || m.role === 'ai') && typeof m.content === 'string')
        .map((m: any) => ({
          role: m.role,
          content: m.content,
          timestamp: typeof m.timestamp === 'string' ? m.timestamp : new Date().toISOString(),
        }));
      return normalized.length ? normalized : DEFAULT_GLOBAL_CHAT_HISTORY;
    } catch {
      return DEFAULT_GLOBAL_CHAT_HISTORY;
    }
  });
  const [chatInput, setChatInput] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [isGeneratingAgent, setIsGeneratingAgent] = useState(false);
  const [isGeneratingGlobal, setIsGeneratingGlobal] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Upload Refs
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  // Model selection
  const [llmConfigs, setLlmConfigs] = useState<any[]>([]);
  const [selectedModel, setSelectedModel] = useState<string | undefined>(undefined);

  // Detail State
  const [customerDetail, setCustomerDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [isEditingDetail, setIsEditingDetail] = useState(false);
  const [editForm, setEditForm] = useState<any>({});
  const [isAutoAnalyzing, setIsAutoAnalyzing] = useState(false);
  const [previewEntry, setPreviewEntry] = useState<any | null>(null);
  
  // Analysis State
  // const [replySuggestion, setReplySuggestion] = useState<any>(null);
  // const [progressionAnalysis, setProgressionAnalysis] = useState<any>(null);
  // const [suggestingReply, setSuggestingReply] = useState(false);
  // const [evaluatingProgression, setEvaluatingProgression] = useState(false);
  // const [isProgressionModalOpen, setIsProgressionModalOpen] = useState(false);
  // const [replyIntent, setReplyIntent] = useState('');

  // View Mode: 'list' | 'detail'
  const [viewMode, setViewMode] = useState<'list' | 'detail'>('list');

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newCustomerName, setNewCustomerName] = useState('');
  const [newCustomerBio, setNewCustomerBio] = useState('');
  const [newCustomerFile, setNewCustomerFile] = useState<File | null>(null);
  
  const [importing, setImporting] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isExcelImportModalOpen, setIsExcelImportModalOpen] = useState(false);
  const [excelImportFile, setExcelImportFile] = useState<File | null>(null);
  const [excelImportHeaders, setExcelImportHeaders] = useState<string[]>([]);
  const [excelSelectedFields, setExcelSelectedFields] = useState<string[]>([]);
  const [excelHeaderLoading, setExcelHeaderLoading] = useState(false);
  const [excelSavingFields, setExcelSavingFields] = useState(false);

  // Batch Delete State
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<number[]>([]);

  useEffect(() => {
    loadCustomers();
  }, []);

  const loadDisplayFields = async () => {
    try {
      const res = await dataSourceApi.getConfigs();
      const fieldSet = new Set<string>();
      (res.data || []).forEach((ds: any) => {
        const configJson = ds.config_json || {};
        const byToken = configJson.display_fields_by_token || {};
        Object.values(byToken).forEach((fields: any) => {
          if (Array.isArray(fields)) {
            fields.forEach((f) => {
              const value = typeof f === 'string' ? f.trim() : '';
              if (value) fieldSet.add(value);
            });
          }
        });
        const excelFields = configJson.display_fields || [];
        if (Array.isArray(excelFields)) {
          excelFields.forEach((f: any) => {
            const value = typeof f === 'string' ? f.trim() : '';
            if (value) fieldSet.add(value);
          });
        }
      });
      setDisplayFields(fieldSet.size > 0 ? Array.from(fieldSet) : []);
    } catch (e) {
      setDisplayFields(null);
    }
  };

  useEffect(() => {
    loadDisplayFields();
  }, []);

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      const capped = globalChatHistory.slice(-200);
      window.localStorage.setItem(GLOBAL_CHAT_STORAGE_KEY, JSON.stringify(capped));
    } catch {
      // ignore
    }
  }, [globalChatHistory]);

  useEffect(() => {
    // Load available LLM configs for model selection
    (async () => {
      try {
        const res = await llmApi.getConfigs();
        setLlmConfigs(res.data || []);
      } catch (e) {
        // silently ignore
      }
    })();
  }, []);

  useEffect(() => {
      const filtered = customers.filter(c => c.name.toLowerCase().includes(searchText.toLowerCase()));
      setFilteredCustomers(filtered);
  }, [searchText, customers]);

  useEffect(() => {
    if (selectedCustomerId) {
        setIsEditingDetail(false);
        loadCustomerDetail(selectedCustomerId);
    } else {
        setCustomerDetail(null);
        setChatHistory([]);
    }
  }, [selectedCustomerId]);

  useEffect(() => {
    if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatHistory, globalChatHistory]);

  const loadCustomers = async () => {
    try {
      const res = await customerApi.getCustomers();
      setCustomers(res.data);
      setFilteredCustomers(res.data);
    } catch (error: any) {
      console.error("Load Customers Error:", error);
      if (error.response) {
          console.error("Error Data:", error.response.data);
          // Show error to user so they can report it
          message.error(`加载客户失败: ${error.response.status} - ${JSON.stringify(error.response.data)}`);
      } else {
          message.error("加载客户失败: 网络错误或服务器未响应");
      }
    } finally {
      setLoading(false);
    }
  };

  const loadCustomerDetail = async (id: number) => {
      setDetailLoading(true);
      try {
          const res = await customerApi.getCustomer(id);
          setCustomerDetail(res.data);
          setEditForm(res.data);
          
          // Parse Customer Logs (Historical) & Agent Chat History
          const logs: ChatMessage[] = [];
          const agentChat: ChatMessage[] = [];

          res.data.data_entries.forEach((entry: any) => {
            if (entry.source_type === 'chat_history_user') {
                logs.push({ role: 'user', content: entry.content, timestamp: entry.created_at });
            } else if (entry.source_type === 'chat_history_ai') {
                logs.push({ role: 'ai', content: entry.content, timestamp: entry.created_at });
            } else if (entry.source_type === 'agent_chat_user') {
                agentChat.push({ role: 'user', content: entry.content, timestamp: entry.created_at });
            } else if (entry.source_type === 'agent_chat_ai') {
                agentChat.push({ role: 'ai', content: entry.content, timestamp: entry.created_at });
            } else if (entry.source_type.startsWith('ai_skill_')) {
                 // Treat skill results as AI messages in the agent chat history
                 const skillName = entry.source_type.replace('ai_skill_', '');
                 // Optionally map skill names to friendly names if needed
                 agentChat.push({ role: 'ai', content: `【${skillName}】\n${entry.content}`, timestamp: entry.created_at });
            }
          });
          
          logs.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
          setCustomerLogs(logs);

          agentChat.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

          // Set Agent Chat (User <-> Agent)
          if (agentChat.length > 0) {
              setChatHistory(agentChat);
          } else {
              setChatHistory([
                  { 
                      role: 'ai', 
                      content: `您好！我是您的专属转化助手。正在分析客户【${res.data.name}】的档案...\n\n您可以点击上方的快捷按钮，或直接向我提问。`, 
                      timestamp: new Date().toISOString() 
                  }
              ]);
          }
      } catch (error) {
          message.error("加载详情失败");
      } finally {
          setDetailLoading(false);
      }
  };

  const parseCustomFields = (value: any) => {
    if (!value) return {};
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === 'object' ? parsed : {};
      } catch {
        return {};
      }
    }
    if (typeof value === 'object') return value;
    return {};
  };

  const getCustomEntriesForDisplay = () => {
    if (!customerDetail) return [];
    const customFields = parseCustomFields(customerDetail.custom_fields) as Record<string, any>;
    const allEntries = Object.entries(customFields);
    if (displayFields === null) return allEntries;
    const allowSet = new Set((displayFields || []).map((v) => (typeof v === 'string' ? v.trim() : '')).filter(Boolean));
    const guards = ['姓名', 'Name', '联系', '电话', '手机', 'Contact', 'Phone', '阶段', 'Stage', '风险', 'Risk'];
    const applyGuards = (entries: Array<[string, any]>) =>
      entries.filter(([k]) => !guards.some((g) => String(k).includes(g)));
    const unguardedAll = applyGuards(allEntries);
    if (allowSet.size === 0) return unguardedAll;
    const filtered = applyGuards(allEntries.filter(([k]) => allowSet.has(k) || allowSet.has(k.trim())));
    if (filtered.length === 0) return unguardedAll;
    return filtered;
  };

  const handleAutoAnalysis = async (id: number) => {
      setIsAutoAnalyzing(true);
      try {
          await customerApi.generateSummary(id);
          // Reload to get new summary
          const res = await customerApi.getCustomer(id);
          setCustomerDetail(res.data);
      } catch (e) {
          console.error("Auto analysis failed", e);
      } finally {
          setIsAutoAnalyzing(false);
      }
  };

  const handleUpdateCustomer = async () => {
      if (!selectedCustomerId) return;
      try {
          await customerApi.updateCustomer(selectedCustomerId, editForm);
          message.success("保存成功");
          setIsEditingDetail(false);
          loadCustomerDetail(selectedCustomerId);
          loadCustomers(); // Refresh list to update name/stage
      } catch (error) {
          message.error("保存失败");
      }
  };

  const handleSendMessage = async () => {
      if (!chatInput.trim()) return;
      const msg = chatInput;
      setChatInput("");
      
      // Global Chat Mode
      if (!selectedCustomerId) {
          setGlobalChatHistory(prev => [...prev, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
          setGlobalChatHistory(prev => [...prev, { role: 'ai', content: '', timestamp: new Date().toISOString() }]);
          setIsGeneratingGlobal(true);
          try {
              await customerApi.chatGlobalStream(msg, selectedModel, {
                  onToken: (token) => {
                      setGlobalChatHistory(prev => {
                          const next = [...prev];
                          const lastIndex = next.length - 1;
                          if (lastIndex >= 0) {
                              const last = next[lastIndex];
                              next[lastIndex] = { ...last, content: `${last.content}${token}` };
                          }
                          return next;
                      });
                  },
                  onError: (errorMessage) => {
                      message.error("发送失败");
                      setIsGeneratingGlobal(false);
                      setGlobalChatHistory(prev => {
                          const next = [...prev];
                          const lastIndex = next.length - 1;
                          if (lastIndex >= 0) {
                              const last = next[lastIndex];
                              const fallback = errorMessage || "(系统错误) 连接 AI 失败，请检查网络或配置。";
                              next[lastIndex] = { ...last, content: `${last.content}${fallback}` };
                          }
                          return next;
                      });
              },
              onDone: () => {
                  setIsGeneratingGlobal(false);
              }
              });
          } catch (error) {
              message.error("发送失败");
          setIsGeneratingGlobal(false);
          }
          return;
      }

      // Customer Agent Chat Mode
      setChatHistory(prev => [...prev, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
      setChatHistory(prev => [...prev, { role: 'ai', content: '', timestamp: new Date().toISOString() }]);
  setIsGeneratingAgent(true);

      const historySnapshot = chatHistory;
      try {
          await customerApi.agentChatStream(selectedCustomerId, msg, historySnapshot, selectedModel, {
              onToken: (token) => {
                  setChatHistory(prev => {
                      const next = [...prev];
                      const lastIndex = next.length - 1;
                      if (lastIndex >= 0) {
                          const last = next[lastIndex];
                          next[lastIndex] = { ...last, content: `${last.content}${token}` };
                      }
                      return next;
                  });
              },
              onError: (errorMessage) => {
                  message.error("发送失败");
              setIsGeneratingAgent(false);
                  setChatHistory(prev => {
                      const next = [...prev];
                      const lastIndex = next.length - 1;
                      if (lastIndex >= 0) {
                          const last = next[lastIndex];
                          const fallback = errorMessage || "思考超时，请重试。";
                          next[lastIndex] = { ...last, content: `${last.content}${fallback}` };
                      }
                      return next;
                  });
      },
      onDone: () => {
          setIsGeneratingAgent(false);
      }
          });
      } catch (error) {
          message.error("发送失败");
      setIsGeneratingAgent(false);
      }
  };

  const handleQuickAsk = async (question: string) => {
      if (!selectedCustomerId) return;
      
      setChatHistory(prev => [...prev, { role: 'user', content: question, timestamp: new Date().toISOString() }]);
      setChatHistory(prev => [...prev, { role: 'ai', content: '', timestamp: new Date().toISOString() }]);
      setIsGeneratingAgent(true);

      const historySnapshot = chatHistory;
      try {
          await customerApi.agentChatStream(selectedCustomerId, question, historySnapshot, selectedModel, {
              onToken: (token) => {
                  setChatHistory(prev => {
                      const next = [...prev];
                      const lastIndex = next.length - 1;
                      if (lastIndex >= 0) {
                          const last = next[lastIndex];
                          next[lastIndex] = { ...last, content: `${last.content}${token}` };
                      }
                      return next;
                  });
              },
              onError: (errorMessage) => {
                  message.error("请求失败");
                  setIsGeneratingAgent(false);
                  setChatHistory(prev => {
                      const next = [...prev];
                      const lastIndex = next.length - 1;
                      if (lastIndex >= 0) {
                          const last = next[lastIndex];
                          const fallback = errorMessage || "助手暂时无法响应，请稍后重试。";
                          next[lastIndex] = { ...last, content: `${last.content}${fallback}` };
                      }
                      return next;
                  });
          },
          onDone: () => {
              setIsGeneratingAgent(false);
          }
          });
      } catch (error) {
          message.error("请求失败");
          setIsGeneratingAgent(false);
      }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      
      const formData = new FormData();
      formData.append('file', file, toSafeUploadFilename(file.name));
      
      setUploading(true);
      try {
          if (selectedCustomerId) {
              // 选中客户：入档并分析
              if (file.type.startsWith('audio/')) {
                   await customerApi.uploadAudio(selectedCustomerId, formData);
                   message.success('语音上传成功，正在转写...');
              } else {
                   await customerApi.uploadDocument(selectedCustomerId, formData);
                   message.success(`${file.type.startsWith('image/') ? '图片' : '文件'}上传成功，已写入档案`);
              }
              loadCustomerDetail(selectedCustomerId);
          } else {
              // 全局模式：不入档，仅分析回答
              if (file.type.startsWith('audio/')) {
                  const res = await customerApi.uploadAudioGlobal(formData);
                  setGlobalChatHistory(prev => [...prev, { role: 'ai', content: res.data.response, timestamp: new Date().toISOString() }]);
                  message.success('已根据通话转写进行分析回复');
              } else if (file.type.startsWith('image/')) {
                  const res = await customerApi.chatGlobalUploadImage(formData);
                  setGlobalChatHistory(prev => [...prev, { role: 'ai', content: res.data.response, timestamp: new Date().toISOString() }]);
                  message.success('已根据图片进行分析回复');
              } else {
                  const res = await customerApi.uploadDocumentGlobal(formData);
                  setGlobalChatHistory(prev => [...prev, { role: 'ai', content: res.data.response, timestamp: new Date().toISOString() }]);
                  message.success('已根据文档内容进行分析回复');
              }
          }
      } catch (error) {
          message.error(getErrorDetail(error) || '上传失败');
      } finally {
          setUploading(false);
          if (fileInputRef.current) fileInputRef.current.value = '';
      }
  };

  const handleCreateCustomer = async () => {
      if (!newCustomerName) return;
      try {
          await customerApi.createCustomer({ 
              name: newCustomerName,
              bio: newCustomerBio,
              file: newCustomerFile
          });
          message.success('创建成功');
          setIsCreateModalOpen(false);
          setNewCustomerName('');
          setNewCustomerBio('');
          setNewCustomerFile(null);
          loadCustomers();
      } catch (error) {
          message.error('创建失败');
      }
  };

  const openExcelImportModal = () => {
    setExcelImportFile(null);
    setExcelImportHeaders([]);
    setExcelSelectedFields([]);
    setIsExcelImportModalOpen(true);
  };

  const parseExcelHeaders = async () => {
    if (!excelImportFile) {
      message.warning('请先选择 Excel 文件');
      return;
    }
    setExcelHeaderLoading(true);
    try {
      const res = await dataSourceApi.getExcelHeaders(excelImportFile);
      const headers = (res.data?.headers || []).filter((h: any) => typeof h === 'string' && h.trim());
      setExcelImportHeaders(headers);
      if (!excelSelectedFields.length && headers.length) {
        setExcelSelectedFields(headers);
      }
    } catch (error) {
      message.error(getErrorDetail(error) || '解析列名失败');
    } finally {
      setExcelHeaderLoading(false);
    }
  };

  const loadExcelFieldsFromImportedData = async () => {
    setExcelHeaderLoading(true);
    try {
      const res = await customerApi.getCustomers();
      const customers = res.data || [];
      const fieldSet = new Set<string>();
      customers.forEach((c: any) => {
        const raw = c?.custom_fields;
        let obj: any = null;
        if (raw && typeof raw === 'string') {
          try {
            obj = JSON.parse(raw);
          } catch {
            obj = null;
          }
        } else if (raw && typeof raw === 'object') {
          obj = raw;
        }
        if (!obj || typeof obj !== 'object') return;
        Object.keys(obj).forEach((k) => {
          const key = typeof k === 'string' ? k.trim() : '';
          if (key) fieldSet.add(key);
        });
      });
      const headers = Array.from(fieldSet).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
      setExcelImportHeaders(headers);
      setExcelSelectedFields(headers);
      if (headers.length === 0) {
        message.info('没有从已导入数据里找到可用字段');
      }
    } catch (error) {
      message.error(getErrorDetail(error) || '从已导入数据加载字段失败');
    } finally {
      setExcelHeaderLoading(false);
    }
  };

  const saveExcelDisplayFields = async (fields: string[]) => {
    const normalized = (fields || []).map((f) => (typeof f === 'string' ? f.trim() : '')).filter(Boolean);
    setExcelSavingFields(true);
    try {
      const res = await dataSourceApi.getConfigs();
      const configs = res.data || [];
      const excelConfig = configs.find((ds: any) => ds?.source_type === 'excel');
      if (excelConfig?.id) {
        await dataSourceApi.updateConfig(excelConfig.id, { config_json: { display_fields: normalized } });
      } else {
        await dataSourceApi.createConfig({ name: 'Excel', source_type: 'excel', config_json: { display_fields: normalized }, is_active: true });
      }
      await loadDisplayFields();
      message.success('Excel 展示字段已保存');
    } catch (error) {
      message.error(getErrorDetail(error) || '保存展示字段失败');
    } finally {
      setExcelSavingFields(false);
    }
  };

  const confirmExcelImport = async () => {
    if (!excelImportFile) {
      message.warning('请先选择 Excel 文件');
      return;
    }
    setImporting(true);
    try {
      if (excelSelectedFields.length) {
        await saveExcelDisplayFields(excelSelectedFields);
      }
      await dataSourceApi.importFromExcel(excelImportFile);
      message.success('导入成功');
      setIsExcelImportModalOpen(false);
      loadCustomers();
    } catch (error) {
      message.error(getErrorDetail(error) || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  const handleDeleteCustomer = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    try {
        await customerApi.deleteCustomer(id);
        message.success('删除成功');
        
        if (selectedCustomerId === id) {
            setSelectedCustomerId(null);
            setViewMode('list');
        }
        
        loadCustomers();
    } catch (error) {
        message.error('删除失败');
    }
  };

  const handleBatchDelete = async () => {
      if (selectedCustomerIds.length === 0) return;
      try {
          await customerApi.batchDeleteCustomers(selectedCustomerIds);
          message.success(`成功删除 ${selectedCustomerIds.length} 位客户`);
          setIsBatchMode(false);
          setSelectedCustomerIds([]);
          loadCustomers();
      } catch (error) {
          message.error("批量删除失败");
      }
  };

  const toggleCustomerSelection = (e: React.MouseEvent, id: number) => {
      e.stopPropagation();
      setSelectedCustomerIds(prev => 
          prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
      );
  };

  const handleDeleteData = async (dataId: number) => {
    if (!selectedCustomerId) return;
    try {
      await customerApi.deleteData(selectedCustomerId, dataId);
      message.success("文件删除成功");
      loadCustomerDetail(selectedCustomerId);
    } catch (error) {
      message.error("删除失败");
    }
  };

  const handleAnalyzeFile = async (filename: string, content: string, sourceType: string) => {
      if (!selectedCustomerId) return;
      setAnalyzing(true);
      try {
          const skillName = 'content_analysis';
          const prompt = `文件名：${filename}\n内容：${content}`;
          
          await customerApi.runSkill(selectedCustomerId, skillName, prompt, selectedModel);
          message.success("智能分析完成");
          loadCustomerDetail(selectedCustomerId);
      } catch (error) {
          message.error(getErrorDetail(error) || "分析失败");
          loadCustomerDetail(selectedCustomerId);
      } finally {
          setAnalyzing(false);
      }
  };


  const getStageColor = (stage: string) => {
      switch(stage) {
          case 'closing': return 'green';
          case 'product_matching': return 'orange';
          case 'trust_building': return 'blue';
          case 'contact_before': return 'default';
          default: return 'default';
      }
  };

  const getStageLabel = (stage: string) => {
      switch(stage) {
          case 'closing': return '商务谈判';
          case 'product_matching': return '需求分析';
          case 'trust_building': return '建立信任';
          case 'contact_before': return '待开发';
          default: return stage;
      }
  };

  const getRiskColor = (risk: string) => {
      if (!risk) return 'default';
      if (risk.includes('高') || risk.includes('激进')) return 'red';
      if (risk.includes('中') || risk.includes('稳健')) return 'orange';
      return 'green';
  };

  const resolveDisplayTitle = (item: any) => {
      if (item?.source_type === 'audio_transcription') {
          const orig = item?.meta_info?.filename || item?.meta_info?.original_audio_filename || '音频转写';
          const stem = typeof orig === 'string' ? orig.replace(/\.[^/.]+$/, '') : '音频转写';
          return `${stem}转写文字`;
      }
      return item?.meta_info?.filename || item?.source_type || '数据';
  };

  // --- UI Components ---

  const renderCustomerSidebar = () => {
      return (
          <div className="flex flex-col h-full bg-white">
              {/* Header: Toggle & Search */}
              <div className="p-4 border-b border-gray-100 flex flex-col gap-3 shrink-0">
                  <div className={`flex items-center ${isSidebarCollapsed ? 'justify-center' : 'justify-between'}`}>
                      {!isSidebarCollapsed && <span className="font-bold text-gray-700">客户导航</span>}
                      <Button 
                          type="text" 
                          icon={isSidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} 
                          onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                      />
                  </div>
                  {!isSidebarCollapsed && (
                      <Input 
                          placeholder="搜索..." 
                          prefix={<SearchOutlined className="text-gray-400" />} 
                          value={searchText}
                          onChange={e => setSearchText(e.target.value)}
                          allowClear
                          className="rounded-lg bg-gray-50"
                      />
                  )}
              </div>
              
              {/* List */}
              <div className="flex-1 overflow-y-auto custom-scrollbar">
                  {filteredCustomers.map(c => (
                      <div 
                          key={c.id}
                          onClick={() => {
                              setSelectedCustomerId(c.id);
                              setViewMode('detail');
                          }}
                          className={`cursor-pointer hover:bg-gray-50 border-b border-gray-50 transition-colors ${
                              isSidebarCollapsed ? 'p-2 py-3' : 'p-3'
                          } ${selectedCustomerId === c.id ? 'bg-blue-50 border-l-4 border-l-blue-500' : 'border-l-4 border-l-transparent'}`}
                          title={c.name}
                      >
                          {isSidebarCollapsed ? (
                              <div className="flex justify-center">
                                  <Avatar style={{ backgroundColor: selectedCustomerId === c.id ? '#1890ff' : '#f0f0f0', color: selectedCustomerId === c.id ? '#fff' : '#999' }}>
                                      {c.name[0]}
                                  </Avatar>
                              </div>
                          ) : (
                              <div className="flex items-center gap-3">
                                  <Avatar size="small" style={{ backgroundColor: selectedCustomerId === c.id ? '#1890ff' : '#f0f0f0', color: selectedCustomerId === c.id ? '#fff' : '#999' }}>
                                      {c.name[0]}
                                  </Avatar>
                                  <div className="flex-1 min-w-0">
                                      <div className={`font-medium truncate ${selectedCustomerId === c.id ? 'text-blue-700' : 'text-gray-700'}`}>
                                          {c.name}
                                      </div>
                                      <div className="text-xs text-gray-400 truncate">
                                          {getStageLabel(c.stage)}
                                      </div>
                                  </div>
                              </div>
                          )}
                      </div>
                  ))}
                  {filteredCustomers.length === 0 && !isSidebarCollapsed && (
                      <div className="p-4 text-center text-gray-400 text-xs">
                          未找到客户
                      </div>
                  )}
              </div>
          </div>
      );
  };

  const renderCustomerGrid = () => (
      <div className="h-full flex flex-col bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
          {/* Header & Search */}
          <div className="p-6 border-b border-gray-100 bg-white">
              <div className="flex justify-between items-center mb-6">
                  <div>
                    <h3 className="text-xl font-bold text-gray-800 m-0">客户列表</h3>
                    <p className="text-gray-400 text-xs mt-1 m-0">共 {filteredCustomers.length} 位客户</p>
                  </div>
                  <div className="flex gap-3">
                      {isBatchMode ? (
                          <>
                              <span className="flex items-center text-gray-500 mr-2">已选 {selectedCustomerIds.length} 项</span>
                              <Button onClick={() => { setIsBatchMode(false); setSelectedCustomerIds([]); }}>取消</Button>
                              <Popconfirm
                                  title={`确定要删除选中的 ${selectedCustomerIds.length} 位客户吗？`}
                                  description="删除后无法恢复，且会同步删除相关聊天记录。"
                                  onConfirm={handleBatchDelete}
                                  okText="确认删除"
                                  cancelText="取消"
                                  disabled={selectedCustomerIds.length === 0}
                              >
                                  <Button danger type="primary" icon={<DeleteOutlined />} disabled={selectedCustomerIds.length === 0}>
                                      批量删除
                                  </Button>
                              </Popconfirm>
                          </>
                      ) : (
                          <>
                              <Button onClick={() => setIsBatchMode(true)}>批量管理</Button>
                              <Tooltip title="批量导入 Excel">
                                  <Button icon={<UploadOutlined />} loading={importing} onClick={openExcelImportModal}>Excel导入</Button>
                              </Tooltip>
                              <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsCreateModalOpen(true)}>新建</Button>
                          </>
                      )}
                  </div>
              </div>
          </div>
          
          {/* Grid List */}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-gray-50/50">
              {filteredCustomers.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到客户" className="mt-20" />
              ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                      {filteredCustomers.map(c => (
                          <div 
                              key={c.id} 
                              onClick={(e) => {
                                  if (isBatchMode) {
                                      toggleCustomerSelection(e, c.id);
                                  } else {
                                      setSelectedCustomerId(c.id);
                                      setViewMode('detail');
                                  }
                              }}
                              className={`p-5 rounded-xl border cursor-pointer transition-all hover:-translate-y-1 hover:shadow-md group bg-white overflow-hidden flex flex-col justify-between ${
                                  (isBatchMode ? selectedCustomerIds.includes(c.id) : selectedCustomerId === c.id)
                                  ? 'border-blue-500 ring-2 ring-blue-100 shadow-sm' 
                                  : 'border-gray-200 hover:border-blue-300'
                              }`}
                          >
                              <div className="flex justify-between items-start mb-3 gap-2">
                                  <div className="flex items-center gap-3 min-w-0 flex-1">
                                      <Avatar 
                                        className="shrink-0"
                                        style={{ backgroundColor: selectedCustomerId === c.id ? '#1890ff' : '#f0f0f0', color: selectedCustomerId === c.id ? '#fff' : '#999' }} 
                                        size="large"
                                      >
                                          {c.name[0]}
                                      </Avatar>
                                      <div className="min-w-0 flex-1">
                                          <div className={`font-bold text-base truncate ${selectedCustomerId === c.id ? 'text-blue-700' : 'text-gray-800'}`}>
                                              {c.name}
                                          </div>
                                          <div className="text-xs text-gray-400 mt-0.5">{new Date(c.created_at).toLocaleDateString()}</div>
                                      </div>
                                  </div>
                                  <div className="flex flex-col items-end gap-2 shrink-0">
                                      <Tooltip title={getStageLabel(c.stage)}>
                                          <Tag bordered={false} color={getStageColor(c.stage)} className="rounded-full px-2 py-0 m-0 max-w-[80px] truncate text-center text-xs scale-90 origin-right">
                                              {getStageLabel(c.stage)}
                                          </Tag>
                                      </Tooltip>
                                      {isBatchMode ? (
                                          <div onClick={(e) => e.stopPropagation()}>
                                              <Checkbox 
                                                  checked={selectedCustomerIds.includes(c.id)} 
                                                  onChange={(e) => toggleCustomerSelection(e as any, c.id)}
                                              />
                                          </div>
                                      ) : (
                                          <Popconfirm
                                              title="确定要删除该客户吗？"
                                              description="删除后无法恢复，且会同步删除相关聊天记录。"
                                              onConfirm={(e) => handleDeleteCustomer(e!, c.id)}
                                              onCancel={(e) => e?.stopPropagation()}
                                              okText="删除"
                                              cancelText="取消"
                                          >
                                              <Button 
                                                  type="text" 
                                                  danger 
                                                  size="small"
                                                  icon={<DeleteOutlined />} 
                                                  onClick={(e) => e.stopPropagation()} 
                                                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                                              />
                                          </Popconfirm>
                                      )}
                                  </div>
                              </div>
                              
                              <div className="mb-4 h-10 shrink-0">
                                  <div className="text-xs text-gray-500 line-clamp-2 leading-relaxed">
                                      {c.summary || "暂无画像摘要，点击让 AI 分析..."}
                                  </div>
                              </div>
                              
                              <div className="flex items-center justify-between pt-3 border-t border-gray-50 gap-2 mt-auto">
                                  <div className="text-xs text-gray-400 truncate flex-1" title={c.contact_info}>
                                      {c.contact_info || '无联系方式'}
                                  </div>
                                  {c.risk_profile && (
                                      <Tooltip title={c.risk_profile}>
                                          <Tag bordered={false} color={getRiskColor(c.risk_profile)} className="mr-0 text-xs scale-90 max-w-[50%] truncate shrink-0">
                                              {c.risk_profile}
                                          </Tag>
                                      </Tooltip>
                                  )}
                              </div>
                          </div>
                      ))}
                  </div>
              )}
          </div>
      </div>
  );

  const renderCustomerDetailView = () => {
    if (!customerDetail || detailLoading) {
        return <div className="h-full flex items-center justify-center bg-white rounded-2xl"><Spin size="large" /></div>;
    }

    return (
        <div className="h-full flex bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            {/* Left: Customer Profile & Summary (30%) */}
            <div className="w-[40%] border-r border-gray-100 flex flex-col bg-gray-50/30">
                 {/* Header */}
                 <div className="p-6 border-b border-gray-100 bg-white">
                    <div className="flex items-center gap-2 mb-4">
                        <Button 
                            type="text" 
                            icon={<ArrowLeftOutlined />} 
                            onClick={() => {
                                setViewMode('list');
                                setSelectedCustomerId(null);
                            }}
                        >
                            返回
                        </Button>
                        <h3 className="text-lg font-bold text-gray-800 m-0 truncate">{customerDetail.name}</h3>
                    </div>
                    
                    <div className="flex flex-wrap gap-2 mb-4">
                        <Tag color={getStageColor(customerDetail.stage)}>{getStageLabel(customerDetail.stage)}</Tag>
                        {customerDetail.risk_profile && (
                            <Tag color={getRiskColor(customerDetail.risk_profile)}>{customerDetail.risk_profile}</Tag>
                        )}
                    </div>
                    
                    <div className="grid grid-cols-2 gap-4 text-xs text-gray-500">
                         <div>
                             <span className="block text-gray-400 mb-1">联系方式</span>
                             {customerDetail.contact_info || '-'}
                         </div>
                         <div>
                             <span className="block text-gray-400 mb-1">创建时间</span>
                             {new Date(customerDetail.created_at).toLocaleDateString()}
                         </div>
                    </div>
                 </div>

                 {/* AI Summary Card */}
                 <div className="p-6 flex-1 overflow-y-auto custom-scrollbar">
                     <div className="bg-white p-5 rounded-xl border border-blue-100 shadow-sm mb-6">
                        <div className="flex justify-between items-center mb-3">
                            <h4 className="flex items-center gap-2 text-blue-800 font-bold m-0 text-sm">
                                <RobotOutlined /> 客户速览
                            </h4>
                            <Button 
                                type="text" 
                                size="small" 
                                icon={<ReloadOutlined spin={isAutoAnalyzing} />} 
                                onClick={() => handleAutoAnalysis(customerDetail.id)}
                                className="text-blue-600 hover:bg-blue-50"
                            >
                                刷新
                            </Button>
                        </div>
                        <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">
                            {customerDetail.summary || (
                                <div className="text-center py-8 text-gray-400">
                                    <RobotOutlined className="text-2xl mb-2" />
                                    <p>暂无画像，点击刷新生成</p>
                                </div>
                            )}
                        </div>
                     </div>

                     {/* Action Buttons */}
                     <div className="space-y-3 mb-6">
                        <Button block onClick={() => setIsEditingDetail(true)}>
                            编辑资料
                        </Button>
                     </div>

                     {/* Basic Info Form */}
                    <Card title="基础信息" variant="borderless" className="shadow-sm rounded-xl mb-6">
                        <div className="grid grid-cols-1 gap-4">
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">客户姓名</label>
                                {isEditingDetail ? (
                                    <Input value={editForm.name} onChange={e => setEditForm({...editForm, name: e.target.value})} />
                                ) : (
                                    <div className="text-gray-800 font-medium">{customerDetail.name}</div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">联系方式</label>
                                {isEditingDetail ? (
                                    <Input value={editForm.contact_info} onChange={e => setEditForm({...editForm, contact_info: e.target.value})} />
                                ) : (
                                    <div className="text-gray-800 font-medium">{customerDetail.contact_info || '未填写'}</div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">销售阶段</label>
                                {isEditingDetail ? (
                                    <Select className="w-full" value={editForm.stage} onChange={val => setEditForm({...editForm, stage: val})}>
                                        <Option value="contact_before">待开发</Option>
                                        <Option value="trust_building">建立信任</Option>
                                        <Option value="product_matching">需求分析</Option>
                                        <Option value="closing">商务谈判</Option>
                                    </Select>
                                ) : (
                                    <div className="text-gray-800 font-medium">{getStageLabel(customerDetail.stage)}</div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">风险偏好</label>
                                {isEditingDetail ? (
                                    <Input value={editForm.risk_profile} onChange={e => setEditForm({...editForm, risk_profile: e.target.value})} />
                                ) : (
                                    <div className="text-gray-800 font-medium">{customerDetail.risk_profile || '未评估'}</div>
                                )}
                            </div>
                            {/* Detailed info rendered here was redundant and removed */}
                            {isEditingDetail && (
                                <Button type="primary" block onClick={handleUpdateCustomer}>保存</Button>
                            )}
                        </div>
                    </Card>

                    {/* Detailed Records (Dynamic Table) */}
                    {(() => {
                        const importRecords = (customerDetail.data_entries || [])
                            .filter((e: any) => e.source_type === 'import_record')
                            .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
                        
                        if (importRecords.length === 0) return null;

                        const allKeys = new Set<string>();
                        importRecords.forEach((r: any) => {
                            if (r.meta_info) {
                                Object.keys(r.meta_info).forEach(k => {
                                    if (k !== 'source_type' && k !== 'source_name') allKeys.add(k);
                                });
                            }
                        });
                        
                        // Sort keys for consistent display? Maybe alphabetically
                        const sortedKeys = Array.from(allKeys).sort();

                        const columns = [
                            ...sortedKeys.map(k => ({ 
                                title: k, 
                                dataIndex: ['meta_info', k], 
                                key: k,
                                render: (text: any) => <span className="text-gray-700">{text || '-'}</span>
                            }))
                        ];

                        return (
                            <Card 
                                title="详细数据" 
                                variant="borderless" 
                                className="shadow-sm rounded-xl mb-6"
                            >
                                <div className="overflow-x-auto">
                                    <Table 
                                        dataSource={importRecords} 
                                        columns={columns} 
                                        rowKey="id" 
                                        pagination={{ pageSize: 5 }} 
                                        size="small"
                                        bordered
                                        scroll={{ x: 'max-content' }}
                                    />
                                </div>
                            </Card>
                        );
                    })()}

                    <Card 
                        title="数据档案" 
                        variant="borderless" 
                        className="shadow-sm rounded-xl"
                        extra={
                            <Tooltip title="上传新文件">
                                <Button 
                                    type="text" 
                                    icon={<PlusOutlined />} 
                                    onClick={() => fileInputRef.current?.click()} 
                                />
                            </Tooltip>
                        }
                    >
                        <List
                            dataSource={[...(customerDetail.data_entries || [])]
                                .filter((e:any) => e.source_type.startsWith('document_') || e.source_type.startsWith('audio_'))
                                .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                            }
                            renderItem={(item: any) => (
                                <List.Item>
                                    <List.Item.Meta
                                        avatar={item.source_type.startsWith('audio_') ? <AudioOutlined className="text-purple-500 text-lg" /> : <FileTextOutlined className="text-blue-500 text-lg" />}
                                        title={
                                            <span className="text-sm font-medium flex items-center gap-2">
                                                <span className="truncate max-w-[120px]" title={resolveDisplayTitle(item)}>{resolveDisplayTitle(item)}</span>
                                                {item.source_type === "audio_transcription_pending" && (
                                                    <Tag color="orange" icon={<LoadingOutlined />}>转写中</Tag>
                                                )}
                                                {item.source_type === "audio_transcription" && (
                                                    <Tag color="green">已转写</Tag>
                                                )}
                                                {item.source_type && item.source_type.startsWith("ai_skill_") && (
                                                    <Tag color="blue">AI 分析</Tag>
                                                )}
                                            </span>
                                        }
                                        description={<span className="text-xs text-gray-400">{new Date(item.created_at).toLocaleString()}</span>}
                                    />
                                    <div className="flex gap-1">
                                        <Button type="text" size="small" onClick={() => setPreviewEntry(item)}>查看</Button>
                                        {(item.source_type === 'audio_transcription' || item.source_type.startsWith('document_')) && (
                                            <Tooltip title={item.source_type.startsWith('audio_') ? "深度分析此通话" : "深度分析此文档"}>
                                                <Button 
                                                    type="text" 
                                                    size="small" 
                                                    icon={<BulbOutlined />} 
                                                    className="text-yellow-500 hover:text-yellow-600" 
                                                    onClick={() => handleAnalyzeFile(item.meta_info?.filename, item.content, item.source_type)}
                                                />
                                            </Tooltip>
                                        )}
                                        <Popconfirm title="确定删除此文件吗？" onConfirm={() => handleDeleteData(item.id)}>
                                            <Button type="text" size="small" icon={<DeleteOutlined />} className="text-gray-400 hover:text-red-500" />
                                        </Popconfirm>
                                    </div>
                                </List.Item>
                            )}
                            locale={{ emptyText: '暂无上传文件' }}
                        />
                    </Card>
                 </div>
            </div>

            {/* Right: Work Area (70%) */}
            <div className="w-[60%] flex flex-col bg-white relative">
                 {/* Agent Header & Quick Actions */}
                 <div className="px-4 py-3 border-b border-gray-100 flex justify-between items-center bg-white shadow-sm z-10">
                    <div className="flex items-center gap-2">
                        <Avatar style={{ backgroundColor: '#722ed1' }} icon={<RobotOutlined />} />
                        <div>
                            <div className="font-bold text-gray-800 text-sm">转化助手</div>
                            <div className="text-xs text-gray-400">辅助决策 / 话术生成</div>
                        </div>
                    </div>
                    <div className="flex gap-2">
                        <Tooltip title="基于客户档案生成画像摘要">
                            <Button size="small" className="text-xs" onClick={() => handleQuickAsk("请帮我生成一份客户速览，包含画像和风险偏好。")}>客户速览</Button>
                        </Tooltip>
                        <Tooltip title="分析最近聊天记录，给出回复建议">
                            <Button size="small" className="text-xs" onClick={() => handleQuickAsk("根据最近的沟通记录，我接下来该怎么回复客户？")}>我该怎么回？</Button>
                        </Tooltip>
                        <Tooltip title="评估当前成交概率与阻碍">
                            <Button size="small" className="text-xs" onClick={() => handleQuickAsk("现在是推进成交的好时机吗？请分析阻碍和下一步建议。")}>现在该不该推？</Button>
                        </Tooltip>
                    </div>
                 </div>

                 {/* Chat History */}
                 <div 
                    className="flex-1 overflow-y-auto p-6 custom-scrollbar space-y-4 bg-gray-50"
                    ref={scrollRef}
                 >
                    <ChatMessageList
                      messages={chatHistory}
                      variant="agent"
                      emptyState={(
                        <div className="text-center py-20 text-gray-400">
                          <RobotOutlined className="text-4xl mb-4" />
                          <p>暂无对话记录，开始沟通吧</p>
                        </div>
                      )}
                    />
                    {isGeneratingAgent && (
                      <div className="flex justify-start mt-2">
                        <div className="bg-white border border-gray-100 px-3 py-2 rounded-xl rounded-tl-none shadow-sm flex items-center gap-2">
                          <Spin size="small" />
                          <span className="text-gray-500 text-xs">正在生成...</span>
                        </div>
                      </div>
                    )}
                 </div>

                 {/* Input Area */}
                 <div className="p-4 border-t border-gray-100 bg-white">
                     <div className="flex gap-3">
                         <Tooltip title="上传文档/图片/音频进行分析">
                             <Button icon={<PaperClipOutlined />} onClick={() => fileInputRef.current?.click()} />
                         </Tooltip>
                         <Input.TextArea 
                             value={chatInput}
                             onChange={e => setChatInput(e.target.value)}
                             onPressEnter={(e) => {
                                 if (!e.shiftKey) {
                                     e.preventDefault();
                                     handleSendMessage();
                                 }
                             }}
                             placeholder="输入问题或指令..."
                             autoSize={{ minRows: 1, maxRows: 4 }}
                             className="rounded-xl resize-none"
                         />
                         <Button type="primary" className="bg-purple-600 hover:bg-purple-500" icon={<SendOutlined />} onClick={handleSendMessage} />
                     </div>
                     <div className="flex justify-between mt-2">
                         <div className="flex gap-1">
                                       <input 
                                         type="file" 
                                         ref={fileInputRef} 
                                         style={{ display: 'none' }} 
                                         accept=".pdf,.doc,.docx,.txt,.csv,.xlsx,.xls,image/*,audio/*" 
                                         onChange={handleFileUpload}
                                       />
                                     </div>
                         <div className="flex justify-between text-xs text-gray-400">
                            <div className="flex gap-2 items-center">
                                <span>当前模型: {selectedModel || '默认'}</span>
                                <Select 
                                    size="small" 
                                    variant="borderless" 
                                    className="w-24 -ml-2 scale-90" 
                                    placeholder="切换模型"
                                    onChange={val => setSelectedModel(val)}
                                    value={selectedModel}
                                >
                                    {llmConfigs.map(config => (
                                        <Option key={config.name} value={config.name}>{config.name}</Option>
                                    ))}
                                </Select>
                            </div>
                            <span>Shift + Enter 换行</span>
                         </div>
                     </div>
                 </div>
            </div>


        </div>
    );
  };

  const renderGlobalChat = () => {
      const currentHistory = globalChatHistory;
      const isGlobal = true;

      return (
          <div className="h-full bg-white rounded-2xl shadow-sm border border-gray-100 flex flex-col overflow-hidden">
              <div className={`px-4 py-3 border-b border-gray-100 flex justify-between items-center z-10 shrink-0 bg-gray-50`}>
                  <div className="flex items-center gap-3 overflow-hidden">
                      <Avatar style={{ backgroundColor: '#52c41a' }} icon={<RobotOutlined />}>
                      </Avatar>
                      <div className="min-w-0">
                          <div className="font-bold text-gray-800 truncate">
                              全局 AI 助手
                          </div>
                          <div className="text-xs text-gray-400 truncate">
                              通用问答 / 系统指令
                          </div>
                      </div>
                  </div>
              </div>

              <div className="flex-1 overflow-hidden relative flex flex-col bg-gray-50/30">
                  <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar" ref={scrollRef}>
                      <ChatMessageList
                        messages={currentHistory}
                        variant="global"
                        emptyState={(
                          <div className="h-full flex flex-col items-center justify-center text-gray-300 space-y-4">
                            <RobotOutlined style={{ fontSize: 48, opacity: 0.2 }} />
                            <p className="text-sm">开始新的对话...</p>
                          </div>
                        )}
                      />
                      {isGeneratingGlobal && (
                        <div className="flex justify-start">
                          <div className="bg-white border border-gray-100 px-3 py-2 rounded-xl rounded-tl-none shadow-sm flex items-center gap-2">
                            <Spin size="small" />
                            <span className="text-gray-500 text-xs">正在生成...</span>
                          </div>
                        </div>
                      )}
                      {analyzing && (
                          <div className="flex justify-start">
                              <div className="bg-white border border-gray-100 px-3 py-2 rounded-xl rounded-tl-none shadow-sm flex items-center gap-2">
                                  <Spin size="small" /> <span className="text-gray-500 text-xs">AI 思考中...</span>
                              </div>
                          </div>
                      )}
                  </div>

                  <div className="shrink-0 bg-white border-t border-gray-100 p-3 z-10">
                      <div className="flex flex-col gap-2 bg-gray-50 p-2 rounded-xl border border-gray-200 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
                          <TextArea 
                              variant="borderless"
                              autoSize={{ minRows: 1, maxRows: 4 }}
                              placeholder="输入通用指令..."
                              value={chatInput}
                              onChange={e => setChatInput(e.target.value)}
                              onPressEnter={(e) => {
                                  if (!e.shiftKey) {
                                      e.preventDefault();
                                      handleSendMessage();
                                  }
                              }}
                              className="text-sm bg-transparent px-1 py-0 custom-scrollbar"
                          />
                          <div className="flex justify-between items-center px-1 pt-1">
                              <div className="flex gap-1">
                                  <Tooltip title="上传文档/图片/音频">
                                      <Button 
                                        type="text" 
                                        size="small" 
                                        icon={<PaperClipOutlined className="text-gray-400 hover:text-blue-500"/>} 
                                        loading={uploading}
                                        onClick={() => fileInputRef.current?.click()}
                                      />
                                  </Tooltip>
                                  <input 
                                      type="file" 
                                      ref={fileInputRef} 
                                      style={{ display: 'none' }} 
                                      accept=".pdf,.doc,.docx,.txt,.csv,.xlsx,.xls,image/*,audio/*" 
                                      onChange={handleFileUpload}
                                  />
                              </div>
                              <div className="flex items-center gap-2">
                                <span>当前模型: {selectedModel || '默认'}</span>
                                <Select
                                  size="small"
                                  variant="borderless"
                                  placeholder="切换模型"
                                  className="w-24 -ml-2 scale-90"
                                  value={selectedModel}
                                  onChange={(v) => setSelectedModel(v)}
                                  allowClear
                                  options={(llmConfigs || []).map((c: any) => ({
                                    label: c.name || `${c.provider || ''}${c.model ? ` / ${c.model}` : ''}`,
                                    value: c.name || c.model || String(c.id || ''),
                                  }))}
                                />
                                <Button 
                                  type="primary" 
                                  shape="circle" 
                                  size="small" 
                                  icon={<SendOutlined />} 
                                  onClick={handleSendMessage} 
                                  disabled={!chatInput.trim()}
                                />
                              </div>
                          </div>
                      </div>
                  </div>
              </div>
          </div>
      );
  };

  return (
    <div className="h-full flex gap-4 overflow-hidden bg-transparent">
       {/* New Sidebar: Column 1 */}
       <div className={`h-full bg-white rounded-2xl shadow-sm border border-gray-100 flex flex-col transition-all duration-300 ${isSidebarCollapsed ? 'w-[70px]' : 'w-[280px]'}`}>
           {renderCustomerSidebar()}
       </div>

       {/* Main Content Area: Column 2 & 3 */}
       <div className="flex-1 h-full flex gap-4 overflow-hidden min-w-0">
          {viewMode === 'detail' ? (
              <div className="w-full h-full glass-card rounded-2xl p-2">
                  {renderCustomerDetailView()}
              </div>
          ) : (
              <>
                  {/* Customer Grid */}
                  <div className="flex-1 h-full flex flex-col min-w-0 glass-card rounded-2xl p-2">
                      {renderCustomerGrid()}
                  </div>
                  
                  {/* Global Chat */}
                  <div className="w-[400px] shrink-0 h-full glass-card rounded-2xl p-2">
                      {renderGlobalChat()}
                  </div>
              </>
          )}
       </div>

       <Modal
         title="Excel 批量导入"
         open={isExcelImportModalOpen}
         onOk={confirmExcelImport}
         onCancel={() => setIsExcelImportModalOpen(false)}
         okText="保存并导入"
         centered
         confirmLoading={importing || excelSavingFields}
       >
         <div className="space-y-3">
           <Upload
             accept=".xlsx,.xls"
             maxCount={1}
             beforeUpload={(file) => {
               setExcelImportFile(file);
               setExcelImportHeaders([]);
               setExcelSelectedFields([]);
               return false;
             }}
             onRemove={() => {
               setExcelImportFile(null);
               setExcelImportHeaders([]);
               setExcelSelectedFields([]);
             }}
           >
             <Button icon={<UploadOutlined />}>选择 Excel 文件</Button>
           </Upload>

           <div className="flex gap-2">
             <Button icon={<FileTextOutlined />} loading={excelHeaderLoading} onClick={parseExcelHeaders} disabled={!excelImportFile}>
               解析列名
             </Button>
             <Button icon={<DatabaseOutlined />} loading={excelHeaderLoading} onClick={loadExcelFieldsFromImportedData}>
               从已导入数据加载字段
             </Button>
             <Button type="primary" loading={excelSavingFields} onClick={() => saveExcelDisplayFields(excelSelectedFields)} disabled={excelSelectedFields.length === 0}>
               保存展示字段
             </Button>
           </div>

           {excelImportHeaders.length > 0 ? (
             <Checkbox.Group
               value={excelSelectedFields}
               onChange={(vals) => setExcelSelectedFields(vals as string[])}
               options={excelImportHeaders.map((h) => ({ label: h, value: h }))}
             />
           ) : (
             <div className="text-xs text-gray-400">请先选择文件并解析列名</div>
           )}
         </div>
       </Modal>

       <Modal  
         title="新建客户档案" 
         open={isCreateModalOpen} 
         onOk={handleCreateCustomer} 
         onCancel={() => setIsCreateModalOpen(false)}
         centered
         okText="创建"
       >
           <div className="space-y-4">
               <div>
                   <label className="block text-sm font-bold text-gray-700 mb-1">客户姓名 <span className="text-red-500">*</span></label>
                   <Input 
                        placeholder="请输入客户姓名" 
                        value={newCustomerName} 
                        onChange={e => setNewCustomerName(e.target.value)} 
                        size="large"
                        prefix={<UserOutlined className="text-gray-400"/>}
                    />
               </div>
               <div>
                   <label className="block text-sm font-bold text-gray-700 mb-1">初始备注 / 简介 (选填)</label>
                   <TextArea 
                        rows={3}
                        placeholder="关于客户的简单描述..." 
                        value={newCustomerBio} 
                        onChange={e => setNewCustomerBio(e.target.value)} 
                    />
               </div>
               <div>
                   <label className="block text-sm font-bold text-gray-700 mb-1">上传初始文档 (选填)</label>
                   <Upload 
                        beforeUpload={(file) => { setNewCustomerFile(file); return false; }}
                        accept=".pdf,.doc,.docx"
                        maxCount={1}
                        onRemove={() => setNewCustomerFile(null)}
                    >
                       <Button icon={<UploadOutlined />}>选择文件 (PDF/Word)</Button>
                    </Upload>
               </div>
           </div>
       </Modal>
       <Modal
         title={previewEntry ? resolveDisplayTitle(previewEntry) : "数据详情"}
         open={!!previewEntry}
         onCancel={() => setPreviewEntry(null)}
         footer={
           previewEntry && (previewEntry.source_type === "audio_transcription" || previewEntry.source_type.startsWith("document_")) && selectedCustomerId
             ? [
                 <Button key="close" onClick={() => setPreviewEntry(null)}>关闭</Button>,
                 <Button
                   key="analyze"
                   type="primary"
                   loading={analyzing}
                   onClick={() => {
                       if (previewEntry) {
                           handleAnalyzeFile(previewEntry.meta_info?.filename || "unknown_file", previewEntry.content, previewEntry.source_type);
                       }
                   }}
                 >
                   {previewEntry.source_type.startsWith('audio_') ? "基于此通话分析" : "基于此文档分析"}
                 </Button>,
               ]
             : [
                 <Button key="close" onClick={() => setPreviewEntry(null)}>关闭</Button>,
               ]
         }
       >
         {previewEntry && (
           <div className="space-y-2">
             <div className="text-xs text-gray-400">
               {previewEntry.created_at && new Date(previewEntry.created_at).toLocaleString()}
             </div>
             <div className="max-h-80 overflow-y-auto whitespace-pre-wrap text-sm text-gray-700">
               {previewEntry.content}
             </div>
           </div>
         )}
       </Modal>
    </div>
  );
};

export default Dashboard;
