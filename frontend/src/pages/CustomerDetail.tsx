import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Card, Typography, Tag, Button, Input, message, Spin, List, Tooltip, Select } from 'antd';
import { ArrowLeftOutlined, RobotOutlined, SendOutlined, FileTextOutlined, AudioOutlined, UploadOutlined, BulbOutlined, SafetyCertificateOutlined, RiseOutlined, DeleteOutlined, LoadingOutlined } from '@ant-design/icons';
import { customerApi, llmApi, dataSourceApi, sessionApi } from '../services/api';
import { Upload, Dropdown, MenuProps, Popconfirm } from 'antd';
import ChatMessageList, { ChatMessage } from '../components/ChatMessageList';
import SessionHeader from '../components/SessionHeader';

const { Header, Content, Sider } = Layout;
const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;
const { Option } = Select;

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

const parseBackendDate = (value: any): Date | null => {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value === 'number') return new Date(value);
  if (typeof value !== 'string') return null;

  const s = value.trim();
  if (!s) return null;

  const hasTimezone = /([zZ]|[+-]\d{2}:\d{2})$/.test(s);
  const iso = hasTimezone ? s : `${s}Z`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d;
};

const formatBackendDate = (value: any) => {
  const d = parseBackendDate(value);
  if (!d) return '-';
  return d.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' });
};

const getBackendTimeMs = (value: any) => {
  const d = parseBackendDate(value);
  return d ? d.getTime() : 0;
};

const CustomerDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [customer, setCustomer] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [llmConfigs, setLlmConfigs] = useState<any[]>([]);
  const [selectedModel, setSelectedModel] = useState<string | undefined>(undefined);
  const [displayFields, setDisplayFields] = useState<string[] | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const loadSessionMessages = useCallback(async (sid: number) => {
    try {
      const res = await sessionApi.getSessionMessages(sid);
      const msgs = (res.data || []).map((m: any) => ({
        role: m.role,
        content: m.content,
        timestamp: m.created_at
      }));
      setChatHistory(msgs);
    } catch (e) {
      message.error("加载消息失败");
    }
  }, []);

  const resetToNewChat = useCallback((customerName?: string) => {
    setSessionId(null);
    setChatHistory([
      {
        role: 'ai',
        content: `您好！我是您的专属转化助手。正在分析客户【${customerName || '当前客户'}】的档案...\n\n您可以点击上方的快捷按钮，或直接向我提问。`,
        timestamp: new Date().toISOString()
      }
    ]);
  }, []);

  const loadCustomer = useCallback(async (customerId: number) => {
    try {
      const res = await customerApi.getCustomer(customerId);
      setCustomer(res.data);

      try {
        const sessionRes = await sessionApi.getSessions(customerId);
        const sessions = sessionRes.data || [];
        if (sessions.length > 0) {
          const latest = sessions[0];
          setSessionId(latest.id);
          await loadSessionMessages(latest.id);
        } else {
          resetToNewChat(res.data?.name);
        }
      } catch (e) {
        resetToNewChat(res.data?.name);
      }
      
    } catch (error) {
      message.error("加载客户失败");
    } finally {
      setLoading(false);
    }
  }, [loadSessionMessages, resetToNewChat]);

  useEffect(() => {
    if (id) loadCustomer(Number(id));
  }, [id, loadCustomer]);

  useEffect(() => {
    const loadModels = async () => {
      try {
        const res = await llmApi.getConfigs();
        setLlmConfigs(res.data || []);
      } catch (e) {
        setLlmConfigs([]);
      }
    };
    loadModels();
  }, []);

  useEffect(() => {
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
        setDisplayFields(fieldSet.size > 0 ? Array.from(fieldSet) : null);
      } catch (e) {
        setDisplayFields(null);
      }
    };
    loadDisplayFields();
  }, []);

  useEffect(() => {
      if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
  }, [chatHistory]);


  const handleGenerateSummary = async () => {
    if (!id) return;
    setAnalyzing(true);
    try {
      const res = await customerApi.generateSummary(Number(id));
      setCustomer(res.data);
      message.success("AI 画像生成成功！");
    } catch (error) {
      message.error("AI 分析失败，请检查 LLM 配置");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleRunSkill = async (skillName: string) => {
    if (!id) return;
    setAnalyzing(true);
    try {
        await customerApi.runSkill(Number(id), skillName, chatInput, selectedModel); 
        message.success("AI 思考完成");
        loadCustomer(Number(id));
    } catch (error) {
        message.error(getErrorDetail(error) || "AI 执行失败");
        loadCustomer(Number(id));
    } finally {
        setAnalyzing(false);
    }
  };

  const handleAudioUpload = async (file: File) => {
    if (!id) return;
    const formData = new FormData();
    formData.append('file', file, toSafeUploadFilename(file.name));
    
    setUploading(true);
    try {
        await customerApi.uploadAudio(Number(id), formData);
        message.success("音频转写成功");
        loadCustomer(Number(id));
    } catch (error) {
        message.error(getErrorDetail(error) || "上传/转写失败");
    } finally {
        setUploading(false);
    }
    return false; 
  };

  const handleDocUpload = async (file: File) => {
    if (!id) return;
    const formData = new FormData();
    formData.append('file', file, toSafeUploadFilename(file.name));
    
    setUploading(true);
    try {
        await customerApi.uploadDocument(Number(id), formData);
        message.success("文件解析成功");
        loadCustomer(Number(id));
    } catch (error) {
        message.error(getErrorDetail(error) || "文件上传失败");
    } finally {
        setUploading(false);
    }
    return false;
  };

  const handleDeleteData = async (dataId: number) => {
    if (!id) return;
    try {
      await customerApi.deleteData(Number(id), dataId);
      message.success("文件删除成功");
      loadCustomer(Number(id));
    } catch (error) {
      message.error("删除失败");
    }
  };

  const handleAnalyzeAudio = async (filename: string, content: string) => {
      if (!id) return;
      setAnalyzing(true);
      try {
          const prompt = `文件名：${filename}\n内容：${content}`;
          await customerApi.runSkill(Number(id), 'content_analysis', prompt, selectedModel);
          message.success("内容分析完成");
          loadCustomer(Number(id));
      } catch (error) {
          message.error(getErrorDetail(error) || "分析失败");
          loadCustomer(Number(id));
      } finally {
          setAnalyzing(false);
      }
  };

  const handleSendMessage = async () => {
      if (!id || !chatInput.trim()) return;
      const msg = chatInput;
      setChatInput("");
      
      setChatHistory(prev => [...prev, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
      setChatHistory(prev => [...prev, { role: 'ai', content: '', timestamp: new Date().toISOString() }]);
      setIsGenerating(true);

      try {
          await customerApi.chatStream(Number(id), msg, selectedModel, {
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
              onEvent: (event, data) => {
                  if (event === 'session_info' && data?.session_id) {
                      setSessionId(data.session_id);
                  }
              },
              onError: (errorMessage) => {
                  message.error("发送失败");
                  setIsGenerating(false);
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
                  setIsGenerating(false);
              }
          }, sessionId || undefined);
      } catch (error) {
          message.error("发送失败");
          setIsGenerating(false);
      }
  };

  const skillMenu: MenuProps['items'] = [
    {
      key: 'core',
      label: '✨ 核心助手',
      icon: <RobotOutlined />,
      onClick: () => handleRunSkill('core'),
    },
    {
      key: 'content_analysis',
      label: '📄 内容分析',
      icon: <FileTextOutlined />,
      onClick: () => handleRunSkill('content_analysis'),
    },
  ];

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

  const formatBasicValue = (label: string, value: any) => {
      if (value === null || value === undefined) return '-';
      if (typeof value === 'string') {
          const trimmed = value.trim();
          if (!trimmed) return '-';
          if ((label.includes('阶段') || label.toLowerCase().includes('stage')) && ['closing', 'product_matching', 'trust_building', 'contact_before'].includes(trimmed)) {
              return getStageLabel(trimmed);
          }
          return trimmed;
      }
      if (typeof value === 'number' || typeof value === 'boolean') return String(value);
      try {
          return JSON.stringify(value);
      } catch {
          return String(value);
      }
  };

  const buildBasicInfoEntries = () => {
      const customFields = parseCustomFields(customer.custom_fields) as Record<string, any>;
      const allEntries = Object.entries(customFields);
      
      if (displayFields === null) {
          const mergedEntries = [...allEntries];
          const baseItems = [
            { label: '客户姓名', value: customer.name, guard: ['姓名', 'Name'] },
            { label: '联系方式', value: customer.contact_info, guard: ['联系', '电话', '手机', 'Contact', 'Phone'] },
            { label: '销售阶段', value: customer.stage, guard: ['阶段', 'Stage'] },
            { label: '风险偏好', value: customer.risk_profile, guard: ['风险', 'Risk'] },
          ];
          const keys = allEntries.map(([k]) => k);
          const hasKeyLike = (patterns: string[]) => keys.some((k) => patterns.some((p) => k.includes(p)));
          
          baseItems.forEach((item) => {
              if (!hasKeyLike(item.guard) && item.value) {
                  mergedEntries.push([item.label, item.value]);
              }
          });
          return mergedEntries;
      }

      const allowedFields = displayFields.map((field) => field.trim()).filter(Boolean);
      const allowSet = new Set(allowedFields);
      
      const filteredEntries = allEntries.filter(([k]) => {
            const trimmedKey = k.trim();
            return allowSet.has(k) || allowSet.has(trimmedKey);
      });
          
      const keys = filteredEntries.map(([k]) => k);
      const hasKeyLike = (patterns: string[]) => keys.some((k) => patterns.some((p) => k.includes(p)));

      const baseItems = [
          { label: '客户姓名', value: customer.name, guard: ['姓名', 'Name'] },
          { label: '联系方式', value: customer.contact_info, guard: ['联系', '电话', '手机', 'Contact', 'Phone'] },
          { label: '销售阶段', value: customer.stage, guard: ['阶段', 'Stage'] },
          { label: '风险偏好', value: customer.risk_profile, guard: ['风险', 'Risk'] },
      ];

      const mergedEntries = [...filteredEntries];
      baseItems.forEach((item) => {
          if (!hasKeyLike(item.guard) && item.value) {
              mergedEntries.push([item.label, item.value]);
          }
      });
      return mergedEntries;
  };

  const handleSessionChange = (sid: number | null) => {
    setSessionId(sid);
    if (sid) {
      loadSessionMessages(sid);
    } else {
      resetToNewChat(customer?.name);
    }
  };

  const handleNewChat = () => {
    resetToNewChat(customer?.name);
  };

  if (loading) return <div className="p-20 text-center"><Spin size="large" /></div>;
  if (!customer) return <div className="p-20 text-center">客户不存在</div>;

  return (
    <Layout className="min-h-screen bg-white">
      <Header className="bg-white border-b px-6 flex items-center justify-between z-10 shadow-sm">
        <div className="flex items-center gap-4">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')} />
          <div>
            <Title level={4} style={{ margin: 0 }}>{customer.name}</Title>
            <Text type="secondary" className="text-xs">上次活跃: {new Date().toLocaleDateString()}</Text>
          </div>
          <Tag color={getStageColor(customer.stage)}>{getStageLabel(customer.stage)}</Tag>
        </div>
        <div className="flex gap-2">
            <Dropdown menu={{ items: skillMenu }}>
                <Button icon={<BulbOutlined />} loading={analyzing}>AI 技能工具箱</Button>
            </Dropdown>
            <Button 
            type="primary" 
            icon={<RobotOutlined />} 
            loading={analyzing}
            onClick={handleGenerateSummary}
            >
            更新画像
            </Button>
        </div>
      </Header>
      
      <Layout>
        <Sider width={350} theme="light" className="border-r bg-gray-50 overflow-y-auto">
           <div className="p-4 space-y-4">
                <Card title="🧠 AI 客户画像" className="shadow-sm border-blue-100" headStyle={{ backgroundColor: '#f0f5ff', color: '#1890ff' }}>
                    {customer.summary ? (
                    <div className="whitespace-pre-wrap text-gray-700 text-sm leading-relaxed">
                        {customer.summary}
                    </div>
                    ) : (
                    <div className="text-gray-400 text-center py-4 text-sm">
                        暂无画像，请点击右上角按钮生成
                    </div>
                    )}
                </Card>
                
                <Card title="📋 基础档案" size="small" className="shadow-sm">
                    {buildBasicInfoEntries().map(([key, value]) => (
                        <p key={key} className="mb-2 text-sm">
                            <Text type="secondary">{key}：</Text>
                            <span className="text-gray-700">{formatBasicValue(key, value)}</span>
                        </p>
                    ))}
                    <div className="mt-4 pt-3 border-t">
                        <p className="mb-0 text-xs text-gray-400"><Text type="secondary" className="text-xs">创建时间：</Text> {formatBackendDate(customer.created_at)}</p>
                    </div>
                </Card>

                <div className="pt-4 border-t">
                    <Title level={5} className="mb-3 text-sm text-gray-500">📁 资料库</Title>
                    <div className="space-y-2">
                        {customer.data_entries
                            .filter((e:any) => e.source_type.startsWith('document_') || e.source_type.startsWith('audio_'))
                            .sort((a: any, b: any) => getBackendTimeMs(b.created_at) - getBackendTimeMs(a.created_at))
                            .map((entry:any) => (
                            <div key={entry.id} className="group flex items-center justify-between p-3 bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-sm transition-all mb-2">
                                <div className="flex items-center gap-3 min-w-0 flex-1">
                                    <div className={`p-2 rounded-lg shrink-0 ${entry.source_type.startsWith('audio_') ? 'bg-purple-50 text-purple-500' : 'bg-blue-50 text-blue-500'}`}>
                                        {entry.source_type.startsWith('audio_') ? <AudioOutlined /> : <FileTextOutlined />}
                                    </div>
                                    <div className="min-w-0 flex-1 flex flex-col">
                                        <div className="flex items-center gap-2">
                                            <Tooltip title={entry.meta_info?.filename}>
                                                <span className="font-medium text-gray-700 truncate text-xs">
                                                    {entry.meta_info?.filename || '未知文件'}
                                                </span>
                                            </Tooltip>
                                            {entry.source_type === 'audio_transcription_pending' && (
                                                <Tag color="orange" icon={<LoadingOutlined />} bordered={false} className="m-0 text-[10px] px-1 scale-90 origin-left shrink-0">转写中</Tag>
                                            )}
                                            {entry.source_type === 'audio_transcription' && (
                                                <Tag color="green" bordered={false} className="m-0 text-[10px] px-1 scale-90 origin-left shrink-0">已转写</Tag>
                                            )}
                                        </div>
                                        <div className="text-[10px] text-gray-400 mt-0.5">
                                            {formatBackendDate(entry.created_at)}
                                        </div>
                                    </div>
                                </div>
                                
                                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-2 shrink-0">
                                    {entry.source_type === 'audio_transcription' && (
                                         <Tooltip title="深度分析此通话">
                                            <Button 
                                                type="text" 
                                                size="small" 
                                                icon={<BulbOutlined />} 
                                                className="text-yellow-500 hover:text-yellow-600 hover:bg-yellow-50 flex items-center justify-center h-6 w-6 rounded" 
                                                onClick={() => handleAnalyzeAudio(entry.meta_info?.filename, entry.content)}
                                            />
                                        </Tooltip>
                                    )}
                                    <Popconfirm title="确定删除此文件吗？" onConfirm={() => handleDeleteData(entry.id)}>
                                        <Button 
                                            type="text" 
                                            size="small" 
                                            icon={<DeleteOutlined />} 
                                            className="text-gray-400 hover:text-red-500 hover:bg-red-50 flex items-center justify-center h-6 w-6 rounded" 
                                        />
                                    </Popconfirm>
                                </div>
                            </div>
                        ))}
                         {customer.data_entries.filter((e:any) => e.source_type.startsWith('document_') || e.source_type.startsWith('audio_')).length === 0 && (
                             <div className="text-xs text-gray-400 text-center">暂无上传资料</div>
                         )}
                    </div>
                </div>
           </div>
        </Sider>
        
        <Content className="bg-white flex flex-col h-[calc(100vh-64px)]">
            <div className="px-6 py-3 border-b bg-white flex items-center justify-end">
                <SessionHeader
                    customerId={customer.id}
                    currentSessionId={sessionId}
                    onSessionChange={handleSessionChange}
                    onNewChat={handleNewChat}
                />
            </div>
            <div className="flex-1 overflow-y-auto p-6 bg-gray-50" ref={scrollRef}>
                <ChatMessageList
                  messages={chatHistory}
                  variant="customer"
                  className="space-y-6 max-w-3xl mx-auto"
                  emptyState={(
                    <div className="h-full flex flex-col items-center justify-center text-gray-300">
                      <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
                      <p>开始与 AI 协作，或录入客户对话...</p>
                    </div>
                  )}
                />
                {isGenerating && (
                  <div className="flex justify-start mt-2 max-w-3xl mx-auto">
                    <div className="bg-white border border-gray-100 px-3 py-2 rounded-xl rounded-tl-none shadow-sm flex items-center gap-2">
                      <Spin size="small" />
                      <span className="text-gray-500 text-xs">正在生成...</span>
                    </div>
                  </div>
                )}
            </div>

            <div className="p-4 border-t bg-white">
                <div className="max-w-3xl mx-auto">
                    <div className="mb-2 flex gap-2">
                        <Upload beforeUpload={handleAudioUpload} showUploadList={false} accept="audio/*">
                            <Button size="small" icon={<AudioOutlined />} loading={uploading}>上传录音</Button>
                        </Upload>
                        <Upload beforeUpload={handleDocUpload} showUploadList={false} accept=".pdf,.doc,.docx,.xlsx,.csv">
                            <Button size="small" icon={<UploadOutlined />} loading={uploading}>上传资料</Button>
                        </Upload>
                        <Select
                          size="small"
                          style={{ width: 140 }}
                          placeholder="切换模型"
                          onChange={(val) => setSelectedModel(val)}
                          value={selectedModel}
                          allowClear
                        >
                          {llmConfigs.map((config) => (
                            <Option key={config.name} value={config.name}>{config.name}</Option>
                          ))}
                        </Select>
                    </div>
                    <div className="flex gap-2">
                        <TextArea 
                            rows={1} 
                            autoSize={{ minRows: 1, maxRows: 4 }}
                            placeholder="输入对话内容，或给 AI 下达指令..." 
                            value={chatInput}
                            onChange={e => setChatInput(e.target.value)}
                            onPressEnter={(e) => {
                                if (!e.shiftKey) {
                                    e.preventDefault();
                                    handleSendMessage();
                                }
                            }}
                            className="flex-1 rounded-xl resize-none"
                        />
                        <Button type="primary" shape="circle" icon={<SendOutlined />} size="large" onClick={handleSendMessage} />
                    </div>
                </div>
            </div>
        </Content>
      </Layout>
    </Layout>
  );
};

export default CustomerDetail;
