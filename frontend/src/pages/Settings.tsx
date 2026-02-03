import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Input, InputNumber, Switch, message, Tabs, Select, Card, Tag, Badge, Popconfirm, Tooltip, Upload, Checkbox } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, DatabaseOutlined, ApiOutlined, RobotOutlined, QuestionCircleOutlined, SyncOutlined, FileTextOutlined, UploadOutlined, ReadOutlined } from '@ant-design/icons';
import { llmApi, dataSourceApi, routingApi, knowledgeApi } from '../services/api';

const { Option } = Select;
const { TextArea } = Input;

const Settings: React.FC = () => {
  const [configs, setConfigs] = useState([]);
  const [dataSources, setDataSources] = useState([]);
  const [routingRules, setRoutingRules] = useState([]);
  const [skillMappings, setSkillMappings] = useState<any[]>([]);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Modals
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isDataSourceModalOpen, setIsDataSourceModalOpen] = useState(false);
  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);
  const [isKnowledgeModalOpen, setIsKnowledgeModalOpen] = useState(false);
  const [isViewModalOpen, setIsViewModalOpen] = useState(false);
  const [viewDoc, setViewDoc] = useState<any>(null);
  
  // Feishu Import State
  const [importing, setImporting] = useState(false);
  // Keyed by datasource ID
  const [savedTokens, setSavedTokens] = useState<Record<number, Array<{alias: string, token: string}>>>({});
  const [displayFieldsByToken, setDisplayFieldsByToken] = useState<Record<number, Record<string, string[]>>>({});
  const [excelDisplayFieldsBySource, setExcelDisplayFieldsBySource] = useState<Record<number, string[]>>({});
  const [headerCache, setHeaderCache] = useState<Record<string, string[]>>({});
  const [headerLoading, setHeaderLoading] = useState<Record<string, boolean>>({});
  const [excelFiles, setExcelFiles] = useState<Record<number, File | null>>({});

  const [form] = Form.useForm();
  const [dsForm] = Form.useForm();
  const [ruleForm] = Form.useForm();
  const [knowledgeForm] = Form.useForm();

  const SYSTEM_SKILLS = [
      { key: 'chat', label: '通用对话', desc: '普通问答与聊天' },
      { key: 'core', label: '核心助手', desc: '转化助手 + 画像 + 风险/推进研判 + 回复建议' },
      { key: 'content_analysis', label: '内容分析', desc: '通话/文件内容统一分析' },
  ];

  const ROUTING_RULE_TARGETS = [
      { key: 'risk_analysis', label: '风险分析' },
      { key: 'deal_evaluation', label: '推进研判' },
  ];

  useEffect(() => {
    loadData();
    const saved = localStorage.getItem('feishu_saved_sheets');
    if (saved) {
        try {
            setSavedTokens(JSON.parse(saved));
        } catch (e) { console.error(e); }
    }
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [llmRes, dsRes, rulesRes, mappingRes, knowRes] = await Promise.all([
          llmApi.getConfigs(),
          dataSourceApi.getConfigs(),
          routingApi.getRules(),
          routingApi.getMappings(),
          knowledgeApi.list()
      ]);
      setConfigs(llmRes.data);
      setDataSources(dsRes.data);
      const displayByToken: Record<number, Record<string, string[]>> = {};
      const excelDisplay: Record<number, string[]> = {};
      (dsRes.data || []).forEach((ds: any) => {
          const configJson = ds.config_json || {};
          if (configJson.display_fields_by_token) {
              displayByToken[ds.id] = configJson.display_fields_by_token;
          }
          if (configJson.display_fields) {
              excelDisplay[ds.id] = configJson.display_fields;
          }
      });
      setDisplayFieldsByToken(displayByToken);
      setExcelDisplayFieldsBySource(excelDisplay);
      setRoutingRules(rulesRes.data);
      setSkillMappings(mappingRes.data);
      setDocuments(knowRes.data);
    } catch (error) {
      console.error(error);
      // Fallback if knowledge api fails (e.g. not ready)
      try {
          const [llmRes, dsRes, rulesRes, mappingRes] = await Promise.all([
              llmApi.getConfigs(),
              dataSourceApi.getConfigs(),
              routingApi.getRules(),
              routingApi.getMappings()
          ]);
          setConfigs(llmRes.data);
          setDataSources(dsRes.data);
          const displayByToken: Record<number, Record<string, string[]>> = {};
          const excelDisplay: Record<number, string[]> = {};
          (dsRes.data || []).forEach((ds: any) => {
              const configJson = ds.config_json || {};
              if (configJson.display_fields_by_token) {
                  displayByToken[ds.id] = configJson.display_fields_by_token;
              }
              if (configJson.display_fields) {
                  excelDisplay[ds.id] = configJson.display_fields;
              }
          });
          setDisplayFieldsByToken(displayByToken);
          setExcelDisplayFieldsBySource(excelDisplay);
          setRoutingRules(rulesRes.data);
          setSkillMappings(mappingRes.data);
      } catch (e) { console.error(e); }
    } finally {
      setLoading(false);
    }
  };

  // ... (Keep Feishu logic)
  const saveToken = (dsId: number, token: string, alias: string = '') => {
      const current = savedTokens[dsId] || [];
      if (current.some(t => t.token === token)) return;
      const newList = [...current, { alias: alias || `Sheet ${current.length + 1}`, token }];
      const newMap = { ...savedTokens, [dsId]: newList };
      setSavedTokens(newMap);
      localStorage.setItem('feishu_saved_sheets', JSON.stringify(newMap));
  };

  const removeToken = (dsId: number, token: string) => {
      const current = savedTokens[dsId] || [];
      const newList = current.filter(t => t.token !== token);
      const newMap = { ...savedTokens, [dsId]: newList };
      setSavedTokens(newMap);
      localStorage.setItem('feishu_saved_sheets', JSON.stringify(newMap));
  };

  const parseFeishuInput = (token: string) => {
      let cleanToken = token;
      let importType = "sheet";
      let tableId = "";
      if (token.includes('/base/') || token.startsWith('bas')) {
          const parts = token.split('/base/');
          if (parts.length > 1) {
              const afterBase = parts[1];
              cleanToken = afterBase.split('?')[0];
              if (afterBase.includes('table=')) {
                  const params = new URLSearchParams(afterBase.split('?')[1]);
                  tableId = params.get('table') || "";
              }
          }
          importType = "bitable";
      } else if (token.includes('/sheets/') || token.startsWith('sht')) {
          if (token.includes('/sheets/')) {
             cleanToken = token.split('/sheets/')[1].split('?')[0];
          }
          importType = "sheet";
      }
      return { cleanToken, importType, tableId };
  };

  const handleFeishuImport = async (token: string, dsId: number) => {
      if (!token) {
          message.warning('Token 不能为空');
          return;
      }
      setImporting(true);
      try {
           const { cleanToken, importType, tableId } = parseFeishuInput(token);
           if (importType === "bitable" && !tableId && token.includes('/base/')) {
               message.info('检测到多维表格，正在尝试导入... (如果失败请确保URL包含 table=xxx)');
           }
           await dataSourceApi.importFeishu(cleanToken, "", importType, tableId, dsId);
           message.success('导入成功');
           saveToken(dsId, cleanToken, '');
      } catch (error) {
          console.error(error);
          const detail = (error as any)?.response?.data?.detail || '未知错误';
          const status = (error as any)?.response?.status;
          if (status === 403 || (typeof detail === 'string' && (detail.includes('No permission') || detail.includes('99991672')))) {
              message.error('导入失败: 无权限。请将企业应用添加为该文档/多维表格的协作者或开启“允许企业应用访问”。并为应用开通 Sheets/Bitable 只读权限。');
          } else {
              message.error('导入失败: ' + detail);
          }
      } finally {
          setImporting(false);
      }
  };

  const handleFetchFeishuHeaders = async (token: string, dsId: number) => {
      if (!token) {
          message.warning('Token 不能为空');
          return;
      }
      const key = `${dsId}:${token}`;
      setHeaderLoading(prev => ({ ...prev, [key]: true }));
      try {
          const { cleanToken, importType, tableId } = parseFeishuInput(token);
          const res = await dataSourceApi.getFeishuHeaders(cleanToken, "", importType, tableId, dsId);
          const headers = res.data?.headers || [];
          setHeaderCache(prev => ({ ...prev, [key]: headers }));
          if (!displayFieldsByToken[dsId]?.[token] && headers.length > 0) {
              setDisplayFieldsByToken(prev => ({
                  ...prev,
                  [dsId]: { ...(prev[dsId] || {}), [token]: headers }
              }));
          }
      } catch (error) {
          message.error('解析列名失败');
      } finally {
          setHeaderLoading(prev => ({ ...prev, [key]: false }));
      }
  };

  const handleSaveFeishuDisplayFields = async (dsId: number, token: string) => {
      const fields = displayFieldsByToken[dsId]?.[token] || [];
      try {
          const current = displayFieldsByToken[dsId] || {};
          await dataSourceApi.updateConfig(dsId, { config_json: { display_fields_by_token: current } });
          message.success('展示字段已保存');
          loadData();
      } catch (error) {
          message.error('保存失败');
      }
  };

  const handleFetchExcelHeaders = async (dsId: number) => {
      const file = excelFiles[dsId];
      if (!file) {
          message.warning('请先选择 Excel 文件');
          return;
      }
      const key = `excel:${dsId}`;
      setHeaderLoading(prev => ({ ...prev, [key]: true }));
      try {
          const res = await dataSourceApi.getExcelHeaders(file);
          const headers = res.data?.headers || [];
          setHeaderCache(prev => ({ ...prev, [key]: headers }));
          if (!excelDisplayFieldsBySource[dsId] && headers.length > 0) {
              setExcelDisplayFieldsBySource(prev => ({ ...prev, [dsId]: headers }));
          }
      } catch (error) {
          message.error('解析列名失败');
      } finally {
          setHeaderLoading(prev => ({ ...prev, [key]: false }));
      }
  };

  const handleSaveExcelDisplayFields = async (dsId: number) => {
      const fields = excelDisplayFieldsBySource[dsId] || [];
      try {
          await dataSourceApi.updateConfig(dsId, { config_json: { display_fields: fields } });
          message.success('展示字段已保存');
          loadData();
      } catch (error) {
          message.error('保存失败');
      }
  };

  const handleExcelImport = async (dsId: number) => {
      const file = excelFiles[dsId];
      if (!file) {
          message.warning('请先选择 Excel 文件');
          return;
      }
      setImporting(true);
      try {
          await dataSourceApi.importFromExcel(file);
          message.success('导入成功');
      } catch (error) {
          message.error('导入失败');
      } finally {
          setImporting(false);
      }
  };

  const handleUpdateMapping = async (skillName: string, configId: number) => {
      try {
          await routingApi.updateMapping(skillName, configId);
          message.success('路由更新成功');
          loadData();
      } catch (error) {
          message.error('更新失败');
      }
  };

  const handleCreateOrUpdateLLM = async (values: any) => {
    try {
      const editingId = (form as any).__editingId;
      if (editingId) {
        await llmApi.updateConfig(editingId, values);
        (form as any).__editingId = undefined;
        message.success('LLM 配置已更新');
      } else {
        await llmApi.createConfig(values);
        message.success('LLM 配置已保存');
      }
      setIsModalOpen(false);
      form.resetFields();
      loadData();
    } catch (error) {
      message.error('保存失败');
    }
  };

  const handleCreateDataSource = async (values: any) => {
      try {
          const payload = {
              name: values.name,
              source_type: values.source_type,
              config_json: {
                  app_id: values.app_id,
                  app_secret: values.app_secret
              },
              is_active: true
          };
          await dataSourceApi.createConfig(payload);
          message.success('数据源已添加');
          setIsDataSourceModalOpen(false);
          dsForm.resetFields();
          loadData();
      } catch (error) {
          message.error('添加失败');
      }
  };

  const handleDeleteDataSource = async (id: number) => {
      try {
          await dataSourceApi.deleteConfig(id);
          message.success('已删除');
          loadData();
      } catch (error) {
          message.error('删除失败');
      }
  };

  const handleCreateRule = async (values: any) => {
      try {
          await routingApi.createRule(values);
          message.success('规则已添加');
          setIsRuleModalOpen(false);
          ruleForm.resetFields();
          loadData();
      } catch (error) {
          message.error('添加失败');
      }
  };

  const handleDeleteRule = async (id: number) => {
      try {
          await routingApi.deleteRule(id);
          message.success('已删除');
          loadData();
      } catch (error) {
          message.error('删除失败');
      }
  };

  const handleAddKnowledge = async (values: any) => {
      try {
          const formData = new FormData();
          formData.append('title', values.title);
          formData.append('category', values.category || 'general');
          
          if (values.file && values.file.fileList && values.file.fileList.length > 0) {
              formData.append('file', values.file.fileList[0].originFileObj);
          } else if (values.content) {
              formData.append('content', values.content);
          } else if (!(form as any).__editingId) {
              message.error('请上传文件或输入内容');
              return;
          }

          if ((form as any).__editingId) {
              await knowledgeApi.update((form as any).__editingId, formData);
              message.success('文档已更新');
          } else {
              await knowledgeApi.add(formData);
              message.success('文档已添加');
          }
          
          setIsKnowledgeModalOpen(false);
          knowledgeForm.resetFields();
          (form as any).__editingId = undefined;
          loadData();
      } catch (error) {
          message.error('操作失败');
      }
  };

  const handleViewKnowledge = async (record: any) => {
      try {
          // Fetch full content if needed, or just use record if content is included in list
          // Usually list might truncate content, so safer to fetch or check
          const res = await knowledgeApi.get(record.id);
          setViewDoc(res.data);
          setIsViewModalOpen(true);
      } catch (e) {
          message.error('获取文档详情失败');
      }
  };

  const handleEditKnowledge = (record: any) => {
      knowledgeForm.setFieldsValue({
          title: record.title,
          category: record.category,
          content: record.content
      });
      (form as any).__editingId = record.id;
      setIsKnowledgeModalOpen(true);
  };

  const handleDeleteKnowledge = async (id: number) => {
      try {
          await knowledgeApi.delete(id);
          message.success('已删除');
          loadData();
      } catch (error) {
          message.error('删除失败');
      }
  };

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '提供商', dataIndex: 'provider', key: 'provider' },
    { title: '模型', dataIndex: 'model_name', key: 'model_name' },
    { title: '总消耗 Token', dataIndex: 'total_tokens', key: 'total_tokens' },
    { title: '总成本 ($)', dataIndex: 'total_cost', key: 'total_cost', render: (val: number) => val.toFixed(4) },
    { 
        title: '状态', 
        dataIndex: 'is_active', 
        key: 'is_active',
        render: (active: boolean) => <Switch checked={active} disabled />
    },
    { 
        title: '操作', 
        key: 'action',
        render: (_: any, record: any) => (
          <div className="flex gap-2">
            <Button type="text" icon={<EditOutlined />} onClick={() => {
              setIsModalOpen(true);
              form.setFieldsValue({
                name: record.name,
                provider: record.provider,
                model_name: record.model_name,
                api_key: record.api_key,
                api_base: record.api_base,
                temperature: record.temperature,
                cost_input_1k: record.cost_input_1k,
                cost_output_1k: record.cost_output_1k,
                is_active: record.is_active
              });
              (form as any).__editingId = record.id;
            }} />
            <Popconfirm title="确认删除该模型？" onConfirm={async () => {
              try {
                await llmApi.deleteConfig(record.id);
                message.success('已删除');
                loadData();
              } catch {
                message.error('删除失败');
              }
            }}>
              <Button type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </div>
        )
    }
  ];

  const dsColumns = [
      { title: '名称', dataIndex: 'name', key: 'name', render: (text: string) => <span className="font-medium">{text}</span> },
      { title: '类型', dataIndex: 'source_type', key: 'source_type', render: (type: string) => <Tag color="blue">{type.toUpperCase()}</Tag> },
      { title: '状态', dataIndex: 'is_active', key: 'active', render: (act: boolean) => <Badge status={act ? "success" : "default"} text={act ? "Active" : "Inactive"} /> },
      { title: '操作', key: 'action', render: (_: any, record: any) => (
          <Popconfirm title="确认删除？" onConfirm={() => handleDeleteDataSource(record.id)}>
              <Button type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
      )}
  ];

  const FeishuRowDetail = ({ record, saved, onSync, onRemove, importing }: any) => {
      const [inputToken, setInputToken] = useState('');
      
      return (
          <div className="p-4 bg-gray-50 rounded-lg">
              <div className="flex gap-2 mb-4">
                  <Input 
                      placeholder="输入飞书表格链接或 Token" 
                      value={inputToken}
                      onChange={e => setInputToken(e.target.value)}
                      style={{ width: 400 }}
                  />
                  <Button type="primary" icon={<SyncOutlined spin={importing} />} onClick={() => onSync(inputToken, record.id)} loading={importing}>
                      立即同步
                  </Button>
              </div>
              <div className="grid grid-cols-4 gap-4">
                  {saved.map((item: any) => (
                      <Card size="small" title={item.alias} extra={
                          <div className="flex gap-1">
                              <Tooltip title="更新数据 (重新导入)">
                                  <Button 
                                      type="text" 
                                      size="small" 
                                      icon={<SyncOutlined />} 
                                      onClick={() => onSync(item.token, record.id)}
                                      loading={importing}
                                      className="text-blue-500 hover:text-blue-600"
                                  >
                                      更新
                                  </Button>
                              </Tooltip>
                              <Tooltip title="移除记录">
                                  <Button 
                                      type="text" 
                                      danger 
                                      size="small" 
                                      onClick={() => onRemove(record.id, item.token)}
                                  >
                                      移除
                                  </Button>
                              </Tooltip>
                          </div>
                      }>
                          <div className="text-xs text-gray-500 break-all">{item.token}</div>
                          <div className="mt-3 space-y-2">
                              <div className="flex gap-2">
                                  <Button size="small" icon={<FileTextOutlined />} loading={headerLoading[`${record.id}:${item.token}`]} onClick={() => handleFetchFeishuHeaders(item.token, record.id)}>
                                      解析列名
                                  </Button>
                                  <Button size="small" type="primary" onClick={() => handleSaveFeishuDisplayFields(record.id, item.token)}>
                                      保存展示字段
                                  </Button>
                              </div>
                              {headerCache[`${record.id}:${item.token}`]?.length > 0 ? (
                                  <Checkbox.Group
                                      value={displayFieldsByToken[record.id]?.[item.token] || []}
                                      onChange={(vals) => {
                                          setDisplayFieldsByToken(prev => ({
                                              ...prev,
                                              [record.id]: { ...(prev[record.id] || {}), [item.token]: vals as string[] }
                                          }));
                                      }}
                                      options={headerCache[`${record.id}:${item.token}`].map((h) => ({ label: h, value: h }))}
                                  />
                              ) : (
                                  <div className="text-xs text-gray-400">暂无列名</div>
                              )}
                          </div>
                      </Card>
                  ))}
              </div>
          </div>
      );
  };

  const ExcelRowDetail = ({ record }: any) => {
      const key = `excel:${record.id}`;
      const headers = headerCache[key] || [];
      const selected = excelDisplayFieldsBySource[record.id] || [];
      return (
          <div className="p-4 bg-gray-50 rounded-lg">
              <div className="flex gap-2 mb-4">
                  <Upload
                      beforeUpload={(file) => {
                          setExcelFiles(prev => ({ ...prev, [record.id]: file }));
                          return false;
                      }}
                      maxCount={1}
                      showUploadList={true}
                  >
                      <Button icon={<UploadOutlined />}>选择 Excel 文件</Button>
                  </Upload>
                  <Button icon={<FileTextOutlined />} loading={headerLoading[key]} onClick={() => handleFetchExcelHeaders(record.id)}>
                      解析列名
                  </Button>
                  <Button type="primary" onClick={() => handleSaveExcelDisplayFields(record.id)}>
                      保存展示字段
                  </Button>
                  <Button onClick={() => handleExcelImport(record.id)} loading={importing}>
                      导入数据
                  </Button>
              </div>
              {headers.length > 0 ? (
                  <Checkbox.Group
                      value={selected}
                      onChange={(vals) => {
                          setExcelDisplayFieldsBySource(prev => ({ ...prev, [record.id]: vals as string[] }));
                      }}
                      options={headers.map((h) => ({ label: h, value: h }))}
                  />
              ) : (
                  <div className="text-xs text-gray-400">暂无列名</div>
              )}
          </div>
      );
  };

  const expandedRowRenderWithExcel = (record: any) => {
      if (record.source_type === 'feishu') {
          const saved = savedTokens[record.id] || [];
          return <FeishuRowDetail record={record} saved={saved} onSync={handleFeishuImport} onRemove={removeToken} importing={importing} />;
      }
      if (record.source_type === 'excel') {
          return <ExcelRowDetail record={record} />;
      }
      return null;
  };

  const skillColumns = [
      { title: '系统功能', dataIndex: 'label', key: 'label', render: (text: string) => <span className="font-bold">{text}</span> },
      { title: '功能描述', dataIndex: 'desc', key: 'desc' },
      { 
          title: '指定执行 LLM', 
          key: 'llm',
          render: (_: any, record: any) => {
                const mapping = skillMappings.find((m: any) => m.skill_name === record.key);
                const currentConfigId = mapping ? mapping.llm_config_id : undefined;
                
                return (
                  <Select 
                    style={{ width: 200 }} 
                    placeholder="默认 (Default)" 
                    value={currentConfigId}
                    onChange={(val) => handleUpdateMapping(record.key, val)}
                  >
                      {configs.map((c: any) => (
                          <Option key={c.id} value={c.id}>{c.name} ({c.provider})</Option>
                      ))}
                  </Select>
              );
          }
      }
  ];

  const ruleColumns = [
      { title: '关键字', dataIndex: 'keyword', key: 'keyword', render: (text: string) => <Tag color="orange">{text}</Tag> },
      { title: '目标技能', dataIndex: 'target_skill', key: 'target_skill', render: (text: string) => <span className="font-bold text-blue-600">{text}</span> },
      { title: '描述', dataIndex: 'description', key: 'description' },
      { title: '操作', key: 'action', render: (_: any, record: any) => (
          <Popconfirm title="确认删除规则？" onConfirm={() => handleDeleteRule(record.id)}>
              <Button type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
      )}
  ];

  const knowledgeColumns = [
      { title: '标题', dataIndex: 'title', key: 'title', render: (text: string) => <span className="font-medium">{text}</span> },
      { title: '分类', dataIndex: 'category', key: 'category', render: (text: string) => <Tag>{text}</Tag> },
      { title: '来源', dataIndex: 'source', key: 'source', render: (text: string) => <span className="text-gray-500 text-xs">{text}</span> },
      { title: '添加时间', dataIndex: 'created_at', key: 'created_at', render: (text: string) => new Date(text).toLocaleString() },
      { title: '操作', key: 'action', render: (_: any, record: any) => (
          <div className="flex gap-2">
            <Tooltip title="查看内容">
                <Button type="text" icon={<ReadOutlined />} onClick={() => handleViewKnowledge(record)} />
            </Tooltip>
            <Tooltip title="编辑">
                <Button type="text" icon={<EditOutlined />} onClick={() => handleEditKnowledge(record)} />
            </Tooltip>
            <Popconfirm title="确认删除？" onConfirm={() => handleDeleteKnowledge(record.id)}>
                <Button type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </div>
      )}
  ];

  const tabItems = [
    {
      key: 'llm',
      label: <span><ApiOutlined />LLM 模型管理</span>,
      children: (
        <>
          <div className="mb-4 flex justify-between items-center">
            <h2 className="text-lg font-bold">LLM 模型配置</h2>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => {
              setIsModalOpen(true);
              form.resetFields();
              (form as any).__editingId = undefined;
            }}>添加模型</Button>
          </div>
          <Table columns={columns} dataSource={configs} rowKey="id" loading={loading} />
        </>
      )
    },
    {
      key: 'datasource',
      label: <span><DatabaseOutlined />数据源接入</span>,
      children: (
        <>
            <div className="mb-4 flex justify-between items-center">
                <h2 className="text-lg font-bold">外部数据源</h2>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsDataSourceModalOpen(true)}>添加数据源</Button>
            </div>
            <Table 
                columns={dsColumns} 
                dataSource={dataSources} 
                rowKey="id" 
                loading={loading}
                expandable={{ expandedRowRender: expandedRowRenderWithExcel }}
            />
        </>
      )
    },
    {
      key: 'knowledge',
      label: <span><ReadOutlined />话术库 & 知识库</span>,
      children: (
        <>
            <div className="mb-4 flex justify-between items-center">
                <h2 className="text-lg font-bold">企业话术库 & 知识库</h2>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => {
                    setIsKnowledgeModalOpen(true);
                    knowledgeForm.resetFields();
                    (form as any).__editingId = undefined;
                }}>添加文档/话术</Button>
            </div>
            <Table 
                columns={knowledgeColumns} 
                dataSource={documents} 
                rowKey="id" 
                loading={loading} 
            />
        </>
      )
    },
    {
      key: 'skills',
      label: <span><RobotOutlined />Skill 路由配置</span>,
      children: (
        <>
            <div className="mb-8">
                <h3 className="text-md font-bold mb-4">系统技能路由矩阵 (System Skills Matrix)</h3>
                <div className="bg-blue-50 p-4 rounded-lg mb-4 text-sm text-blue-700">
                    <QuestionCircleOutlined /> 配置每个系统核心功能（Skill）使用哪个 LLM 模型执行。
                    例如：简单的闲聊可以使用便宜的模型 (gpt-3.5)，而复杂的画像生成可以使用强大的模型 (gpt-4)。
                </div>
                <Table columns={skillColumns} dataSource={SYSTEM_SKILLS} pagination={false} rowKey="key" />
            </div>

            <div>
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-md font-bold">关键词触发规则 (Trigger Rules)</h3>
                    <Button type="dashed" icon={<PlusOutlined />} onClick={() => setIsRuleModalOpen(true)}>添加规则</Button>
                </div>
                <Table columns={ruleColumns} dataSource={routingRules} rowKey="id" />
            </div>
        </>
      )
    }
  ];

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm h-full overflow-y-auto">
      <Tabs defaultActiveKey="llm" items={tabItems} />

      {/* LLM Modal */}
      <Modal title="配置 LLM" open={isModalOpen} onOk={() => form.submit()} onCancel={() => setIsModalOpen(false)}>
        <Form form={form} layout="vertical" onFinish={handleCreateOrUpdateLLM}>
          <Form.Item name="name" label="配置名称" rules={[{ required: true }]}>
            <Input placeholder="例如: GPT-4 Production" />
          </Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select>
              <Option value="openai">OpenAI</Option>
              <Option value="anthropic">Anthropic</Option>
              <Option value="azure">Azure OpenAI</Option>
              <Option value="local">Local (Ollama/vLLM)</Option>
              <Option value="volcengine">火山引擎 (Doubao)</Option>
            </Select>
          </Form.Item>
          <Form.Item name="model_name" label="模型名称 (Model ID)" rules={[{ required: true }]}>
            <Input placeholder="例如: gpt-4-turbo, claude-3-opus" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="api_base" label="API Base URL (Optional)">
            <Input placeholder="例如: https://api.openai.com/v1" />
          </Form.Item>
          <div className="grid grid-cols-2 gap-4">
            <Form.Item name="temperature" label="Temperature">
              <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="is_active" label="是否启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Form.Item name="cost_input_1k" label="输入成本 ($/1k tokens)">
               <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="cost_output_1k" label="输出成本 ($/1k tokens)">
               <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      {/* DataSource Modal */}
      <Modal title="添加数据源" open={isDataSourceModalOpen} onOk={() => dsForm.submit()} onCancel={() => setIsDataSourceModalOpen(false)}>
          <Form form={dsForm} layout="vertical" onFinish={handleCreateDataSource}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                  <Input />
              </Form.Item>
              <Form.Item name="source_type" label="类型" initialValue="feishu">
                  <Select>
                      <Option value="feishu">飞书多维表格 (Feishu Base)</Option>
                      <Option value="excel">Excel 表格</Option>
                      <Option value="mysql">MySQL Database</Option>
                  </Select>
              </Form.Item>
              <Form.Item name="app_id" label="App ID">
                  <Input />
              </Form.Item>
              <Form.Item name="app_secret" label="App Secret">
                  <Input.Password />
              </Form.Item>
          </Form>
      </Modal>

      {/* Rule Modal */}
      <Modal title="添加路由规则" open={isRuleModalOpen} onOk={() => ruleForm.submit()} onCancel={() => setIsRuleModalOpen(false)}>
          <Form form={ruleForm} layout="vertical" onFinish={handleCreateRule}>
              <Form.Item name="keyword" label="关键词" rules={[{ required: true }]}>
                  <Input placeholder="例如: 价格, 投诉, 技术问题" />
              </Form.Item>
              <Form.Item name="target_skill" label="目标技能" rules={[{ required: true }]}>
                  <Select>
                      {ROUTING_RULE_TARGETS.map(s => <Option key={s.key} value={s.key}>{s.label}</Option>)}
                  </Select>
              </Form.Item>
              <Form.Item name="description" label="描述">
                  <Input />
              </Form.Item>
          </Form>
      </Modal>

      {/* Knowledge Modal */}
      <Modal 
        title={(form as any).__editingId ? "编辑文档/话术" : "添加文档/话术"} 
        open={isKnowledgeModalOpen} 
        onOk={() => knowledgeForm.submit()} 
        onCancel={() => setIsKnowledgeModalOpen(false)}
      >
        <Form form={knowledgeForm} layout="vertical" onFinish={handleAddKnowledge}>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="例如: 高净值客户话术 V1" />
          </Form.Item>
          <Form.Item name="category" label="分类" initialValue="general">
             <Select>
                 <Option value="general">通用知识 (General)</Option>
                 <Option value="sales_script">销售话术 (Script)</Option>
                 <Option value="product_info">产品资料 (Product)</Option>
                 <Option value="competitor">竞品分析 (Competitor)</Option>
             </Select>
          </Form.Item>
          
          <Tabs 
            defaultActiveKey="text"
            items={[
                {
                    key: 'text',
                    label: '手动输入',
                    children: (
                        <Form.Item name="content" label="内容">
                            <TextArea rows={10} placeholder="输入文档内容或话术..." />
                        </Form.Item>
                    )
                },
                {
                    key: 'file',
                    label: '文件上传',
                    children: (
                        <Form.Item name="file" label="上传文件 (支持 .txt, .md)">
                            <Upload maxCount={1} beforeUpload={() => false}>
                                <Button icon={<UploadOutlined />}>选择文件</Button>
                            </Upload>
                        </Form.Item>
                    )
                }
            ]}
          />
        </Form>
      </Modal>

      {/* View Modal */}
      <Modal
        title={viewDoc?.title || "文档详情"}
        open={isViewModalOpen}
        onCancel={() => setIsViewModalOpen(false)}
        footer={[<Button key="close" onClick={() => setIsViewModalOpen(false)}>关闭</Button>]}
        width={800}
      >
          <div className="mb-4">
              <Tag color="blue">{viewDoc?.category}</Tag>
              <span className="text-gray-500 ml-2">来源: {viewDoc?.source}</span>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg max-h-[60vh] overflow-y-auto whitespace-pre-wrap">
              {viewDoc?.content}
          </div>
      </Modal>
    </div>
  );
};

export default Settings;
