import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Card, Typography, Tag, Button, Input, message, Spin, Avatar, List, Tooltip } from 'antd';
import { ArrowLeftOutlined, RobotOutlined, SendOutlined, FileTextOutlined, AudioOutlined, UploadOutlined, UserOutlined, BulbOutlined, SafetyCertificateOutlined, RiseOutlined, DeleteOutlined, LoadingOutlined } from '@ant-design/icons';
import { customerApi } from '../services/api';
import { Upload, Dropdown, MenuProps, Popconfirm } from 'antd';

const { Header, Content, Sider } = Layout;
const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface ChatMessage {
    role: 'user' | 'ai';
    content: string;
    timestamp: string;
}

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

const CustomerDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [customer, setCustomer] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (id) loadCustomer(Number(id));
  }, [id]);

  useEffect(() => {
      // Scroll to bottom when chat history updates
      if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
  }, [chatHistory]);

  const loadCustomer = async (customerId: number) => {
    try {
      const res = await customerApi.getCustomer(customerId);
      setCustomer(res.data);
      
      // Parse chat history from data entries
      const history: ChatMessage[] = [];
      res.data.data_entries.forEach((entry: any) => {
          if (entry.source_type === 'chat_history_user') {
              history.push({ role: 'user', content: entry.content, timestamp: entry.created_at });
          } else if (entry.source_type === 'chat_history_ai') {
              history.push({ role: 'ai', content: entry.content, timestamp: entry.created_at });
          } else if (entry.source_type.startsWith('ai_skill_')) {
               // Treat skill results as AI messages
               const skillName = entry.source_type.replace('ai_skill_', '');
               history.push({ role: 'ai', content: `【${skillName}】\n${entry.content}`, timestamp: entry.created_at });
          }
      });
      // Sort by time
      history.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
      setChatHistory(history);
      
    } catch (error) {
      message.error("加载客户失败");
    } finally {
      setLoading(false);
    }
  };

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
        await customerApi.runSkill(Number(id), skillName, chatInput); 
        message.success("AI 思考完成");
        loadCustomer(Number(id)); // Refresh to see result
    } catch (error) {
        message.error("AI 执行失败");
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
          // Construct a prompt to analyze this specific audio
          const prompt = `请对以下通话录音进行深度分析（包含核心摘要、关键信息、客户情绪、销售机会）：\n\n文件名：${filename}\n内容：${content}`;
          // Use 'call_analysis' skill or just a generic chat/agent command? 
          // The user mentioned "based on this call". Let's use 'call_analysis' skill but with specific instruction.
          // However, api.runSkill takes (id, skillName, question).
          await customerApi.runSkill(Number(id), 'call_analysis', prompt);
          message.success("通话分析完成");
          loadCustomer(Number(id));
      } catch (error) {
          message.error("分析失败");
      } finally {
          setAnalyzing(false);
      }
  };

  const handleSendMessage = async () => {
      if (!id || !chatInput.trim()) return;
      const msg = chatInput;
      setChatInput("");
      
      // Optimistic update
      setChatHistory(prev => [...prev, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
      
      try {
          // Send to backend (using chat API)
          await customerApi.chat(Number(id), msg);
          loadCustomer(Number(id)); // Refresh to get AI response
      } catch (error) {
          message.error("发送失败");
      }
  };

  const skillMenu: MenuProps['items'] = [
    {
      key: 'call_analysis',
      label: '📞 通话深度分析',
      icon: <AudioOutlined />,
      onClick: () => handleRunSkill('call_analysis'),
    },
    {
      key: 'risk_analysis',
      label: '🛡️ 深度风险分析',
      icon: <SafetyCertificateOutlined />,
      onClick: () => handleRunSkill('risk_analysis'),
    },
    {
      key: 'deal_evaluation',
      label: '⚖️ 推进可行性研判',
      icon: <RiseOutlined />,
      onClick: () => handleRunSkill('deal_evaluation'),
    },
    {
        key: 'reply_suggestion',
        label: '💬 生成回复建议',
        icon: <BulbOutlined />,
        onClick: () => handleRunSkill('reply_suggestion'),
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
                    <p className="mb-2"><Text type="secondary">联系方式：</Text> {customer.contact_info || '-'}</p>
                    <p className="mb-2"><Text type="secondary">风险偏好：</Text> {customer.risk_profile || '-'}</p>
                    
                    {/* Dynamic Fields with Robust Handling */}
                    {(() => {
                        let fields = customer.custom_fields;
                        let hasCustomFields = false;

                        // Handle potential JSON string from backend or null
                        if (fields) {
                            if (typeof fields === 'string') {
                                try {
                                    fields = JSON.parse(fields);
                                } catch (e) {
                                    console.error("Failed to parse custom_fields", e);
                                    fields = {};
                                }
                            }
                            if (fields && typeof fields === 'object' && Object.keys(fields).length > 0) {
                                hasCustomFields = true;
                            }
                        }

                        if (!hasCustomFields) {
                            return (
                                <div className="mt-4 pt-3 border-t border-dashed border-gray-200">
                                    <Text type="secondary" className="text-xs text-gray-400">暂无其他扩展信息 (可通过 Excel/飞书导入)</Text>
                                </div>
                            );
                        }

                        return (
                            <div className="mt-3 pt-3 border-t border-dashed border-gray-200">
                                <Text type="secondary" className="block mb-2 text-xs font-bold text-gray-500">扩展信息</Text>
                                {Object.entries(fields).map(([key, value]) => (
                                    <p key={key} className="mb-2 text-sm">
                                        <Text type="secondary">{key}：</Text> 
                                        <span className="text-gray-700">{String(value)}</span>
                                    </p>
                                ))}
                            </div>
                        );
                    })()}

                    <div className="mt-4 pt-3 border-t">
                        <p className="mb-0 text-xs text-gray-400"><Text type="secondary" className="text-xs">创建时间：</Text> {new Date(customer.created_at).toLocaleDateString()}</p>
                    </div>
                </Card>

                <div className="pt-4 border-t">
                    <Title level={5} className="mb-3 text-sm text-gray-500">📁 资料库</Title>
                    <div className="space-y-2">
                        {customer.data_entries
                            .filter((e:any) => e.source_type.startsWith('document_') || e.source_type.startsWith('audio_'))
                            .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
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
                                            {new Date(entry.created_at).toLocaleDateString()}
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
            {/* Chat Area */}
            <div className="flex-1 overflow-y-auto p-6 bg-gray-50" ref={scrollRef}>
                {chatHistory.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-gray-300">
                        <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
                        <p>开始与 AI 协作，或录入客户对话...</p>
                    </div>
                ) : (
                    <div className="space-y-6 max-w-3xl mx-auto">
                        {chatHistory.map((msg, idx) => (
                            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                <div className={`flex gap-3 max-w-[80%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                                    <Avatar 
                                        icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />} 
                                        className={msg.role === 'user' ? 'bg-blue-500' : 'bg-green-500'} 
                                    />
                                    <div className={`p-3 rounded-xl shadow-sm whitespace-pre-wrap ${
                                        msg.role === 'user' 
                                            ? 'bg-blue-500 text-white rounded-tr-none' 
                                            : 'bg-white border text-gray-700 rounded-tl-none'
                                    }`}>
                                        {msg.content}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Input Area */}
            <div className="p-4 border-t bg-white">
                <div className="max-w-3xl mx-auto">
                    <div className="mb-2 flex gap-2">
                        <Upload beforeUpload={handleAudioUpload} showUploadList={false} accept="audio/*">
                            <Button size="small" icon={<AudioOutlined />} loading={uploading}>上传录音</Button>
                        </Upload>
                        <Upload beforeUpload={handleDocUpload} showUploadList={false} accept=".pdf,.doc,.docx,.xlsx,.csv,.txt">
                            <Button size="small" icon={<UploadOutlined />} loading={uploading}>上传资料</Button>
                        </Upload>
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
