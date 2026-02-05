import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Input, InputNumber, Switch, message, Tabs, Select, Card, Tag, Badge, Popconfirm, Tooltip, Upload, Checkbox } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, DatabaseOutlined, ApiOutlined, RobotOutlined, QuestionCircleOutlined, SyncOutlined, FileTextOutlined, UploadOutlined, ReadOutlined } from '@ant-design/icons';
import { llmApi, dataSourceApi, routingApi, knowledgeApi, scriptApi } from '../services/api';

const { Option } = Select;
const { TextArea } = Input;

const formatDateTime = (value?: string) => {
  if (!value) return '';
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(value);
  const pure = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value);
  const target = !hasTz && pure ? `${value}Z` : value;
  const date = new Date(target);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const Settings: React.FC = () => {
  const [configs, setConfigs] = useState([]);
  const [dataSources, setDataSources] = useState([]);
  const [routingRules, setRoutingRules] = useState([]);
  const [skillMappings, setSkillMappings] = useState<any[]>([]);
  const [documents, setDocuments] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [knowledgeMode, setKnowledgeMode] = useState<'knowledge' | 'script'>('knowledge');
  const [scriptsLoading, setScriptsLoading] = useState(false);
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
  const [headerCache, setHeaderCache] = useState<Record<string, string[]>>({});
  const [headerLoading, setHeaderLoading] = useState<Record<string, boolean>>({});
  const [isKnowledgeImportModalOpen, setIsKnowledgeImportModalOpen] = useState(false);
  const [knowledgeImportHeaders, setKnowledgeImportHeaders] = useState<string[]>([]);
  const [knowledgeImportLoading, setKnowledgeImportLoading] = useState(false);
  const [isScriptImportModalOpen, setIsScriptImportModalOpen] = useState(false);
  const [scriptImportHeaders, setScriptImportHeaders] = useState<string[]>([]);
  const [scriptImportLoading, setScriptImportLoading] = useState(false);

  const [form] = Form.useForm();
  const [dsForm] = Form.useForm();
  const [ruleForm] = Form.useForm();
  const [knowledgeForm] = Form.useForm();
  const [knowledgeImportForm] = Form.useForm();
  const [scriptImportForm] = Form.useForm();

  const SYSTEM_SKILLS = [
      { key: 'core', name: '核心助手', description: '统一处理画像生成、回复建议、推进评估与智能对话' },
      { key: 'chat', name: '通用对话', description: '默认的问答与闲聊能力' },
      { key: 'data_selector', name: '数据检索', description: 'RAG 检索时选择最相关的数据源' },
      { key: 'knowledge_processing', name: '知识/话术预处理', description: '导入知识库或话术时的 AI 清洗与结构化' },
  ];

  const ROUTING_RULE_TARGETS = [
      { key: 'risk_analysis', label: '风险分析' },
      { key: 'deal_evaluation', label: '推进研判' },
  ];

  useEffect(() => {
    loadData();
    loadScripts();
    const saved = localStorage.getItem('feishu_saved_sheets');
    if (saved) {
        try {
            setSavedTokens(JSON.parse(saved));
        } catch (e) { console.error(e); }
    }
  }, []);

  useEffect(() => {
    knowledgeForm.resetFields();
    (form as any).__editingId = undefined;
  }, [form, knowledgeForm, knowledgeMode]);

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
      (dsRes.data || []).forEach((ds: any) => {
          const configJson = ds.config_json || {};
          if (configJson.display_fields_by_token) {
              displayByToken[ds.id] = configJson.display_fields_by_token;
          }
      });
      setDisplayFieldsByToken(displayByToken);
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
          (dsRes.data || []).forEach((ds: any) => {
              const configJson = ds.config_json || {};
              if (configJson.display_fields_by_token) {
                  displayByToken[ds.id] = configJson.display_fields_by_token;
              }
          });
          setDisplayFieldsByToken(displayByToken);
          setRoutingRules(rulesRes.data);
          setSkillMappings(mappingRes.data);
      } catch (e) { console.error(e); }
    } finally {
      setLoading(false);
    }
  };

  const loadScripts = async () => {
    setScriptsLoading(true);
    try {
      const res = await scriptApi.getScripts();
      setScripts(res.data || []);
    } catch (error) {
      message.error('加载话术库失败');
    } finally {
      setScriptsLoading(false);
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
      let viewId = "";
      
      if (token.includes('/base/') || token.startsWith('bas')) {
          const parts = token.split('/base/');
          if (parts.length > 1) {
              const afterBase = parts[1];
              cleanToken = afterBase.split('?')[0];
              const query = afterBase.includes('?') ? afterBase.split('?')[1] : '';
              if (query) {
                  const params = new URLSearchParams(query);
                  tableId = params.get('table') || "";
                  viewId = params.get('view') || "";
              }
          } else {
              cleanToken = token.split('?')[0];
              const query = token.includes('?') ? token.split('?')[1] : '';
              if (query) {
                  const params = new URLSearchParams(query);
                  tableId = params.get('table') || "";
                  viewId = params.get('view') || "";
              }
          }
          importType = "bitable";
      } else if (token.includes('/sheets/') || token.startsWith('sht')) {
          if (token.includes('/sheets/')) {
             const afterSheets = token.split('/sheets/')[1];
             cleanToken = afterSheets.split('?')[0];
          }
          if (token.includes('?')) {
              const query = token.split('?')[1];
              const params = new URLSearchParams(query);
              viewId = params.get('view') || "";
          }
          importType = "sheet";
      } else if (token.includes('/docx/') || token.includes('/docs/') || token.startsWith('dox')) {
          // Handle Docx / Docs
          if (token.includes('/docx/')) {
              const afterDocx = token.split('/docx/')[1];
              cleanToken = afterDocx.split('?')[0];
          } else if (token.includes('/docs/')) {
              const afterDocs = token.split('/docs/')[1];
              cleanToken = afterDocs.split('?')[0];
          }
          importType = "docx";
      }
      return { cleanToken, importType, tableId, viewId };
  };

  const handleFeishuImport = async (token: string, dsId: number) => {
      if (!token) {
          message.warning('Token 不能为空');
          return;
      }
      setImporting(true);
      try {
           const { cleanToken, importType, tableId, viewId } = parseFeishuInput(token);
           if (importType === "bitable" && !tableId) {
               message.error('多维表格链接需要包含 table=xxx');
               return;
           }
           if (importType === "docx") {
               message.info('检测到文档，正在导入...');
           }
           await dataSourceApi.importFeishu(cleanToken, "", importType, tableId, dsId, viewId);
           message.success('导入成功');
           saveToken(dsId, token, '');
      } catch (error) {
          console.error(error);
          const detail = (error as any)?.response?.data?.detail || '未知错误';
          const status = (error as any)?.response?.status;
          if (status === 403 || (typeof detail === 'string' && (detail.includes('No permission') || detail.includes('99991672')))) {
              message.error('导入失败: 无权限。请将企业应用添加为该文档/多维表格的协作者或开启“允许企业应用访问”。并为应用开通 Sheets/Bitable/Docx 只读权限。');
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
          const { cleanToken, importType, tableId, viewId } = parseFeishuInput(token);
          if (importType === "docx") {
              message.info("文档类型无需解析列名");
              return;
          }
          if (importType === "bitable" && !tableId) {
              message.error('多维表格链接需要包含 table=xxx');
              return;
          }
          const res = await dataSourceApi.getFeishuHeaders(cleanToken, "", importType, tableId, dsId, viewId);
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

  const handleFetchKnowledgeHeaders = async () => {
      const values = knowledgeImportForm.getFieldsValue();
      const token = values.token;
      const dsId = values.data_source_id;
      if (!token || !dsId) {
          message.warning('请先选择数据源并填写表格地址或 Token');
          return;
      }
      setKnowledgeImportLoading(true);
      try {
          const { cleanToken, importType, tableId, viewId } = parseFeishuInput(token);
          if (importType === "bitable" && !tableId) {
              message.error('多维表格链接需要包含 table=xxx');
              return;
          }
          const res = await dataSourceApi.getFeishuHeaders(cleanToken, "", importType, tableId, dsId, viewId);
          const headers = res.data?.headers || [];
          setKnowledgeImportHeaders(headers);
          if (headers.length > 0) {
              const titleField = values.title_field || headers[0];
              const contentFields = values.content_fields && values.content_fields.length > 0
                  ? values.content_fields
                  : headers.filter((h: string) => h !== titleField);
              knowledgeImportForm.setFieldsValue({
                  title_field: titleField,
                  content_fields: contentFields
              });
          }
      } catch (error) {
          message.error('解析列名失败');
      } finally {
          setKnowledgeImportLoading(false);
      }
  };

  const handleImportKnowledgeFromSource = async (values: any) => {
      const token = values.token;
      const dsId = values.data_source_id;
      if (!token || !dsId) {
          message.warning('请先选择数据源并填写表格地址或 Token');
          return;
      }
      setKnowledgeImportLoading(true);
      try {
          const { cleanToken, importType, tableId, viewId } = parseFeishuInput(token);
          if (importType === "bitable" && !tableId) {
              message.error('多维表格链接需要包含 table=xxx');
              return;
          }
          const res = await knowledgeApi.importFeishu({
              spreadsheet_token: cleanToken,
              range_name: "",
              import_type: importType,
              table_id: tableId,
              view_id: viewId,
              data_source_id: dsId,
              category: values.category || 'general',
              title_field: values.title_field || null,
              content_fields: values.content_fields || [],
              use_ai_processing: values.use_ai_processing
          });
          const imported = res.data?.imported ?? 0;
          const skipped = res.data?.skipped ?? 0;
          message.success(`导入完成：成功 ${imported} 条，跳过 ${skipped} 条`);
          setIsKnowledgeImportModalOpen(false);
          knowledgeImportForm.resetFields();
          setKnowledgeImportHeaders([]);
          loadData();
      } catch (error) {
          const detail = (error as any)?.response?.data?.detail || '导入失败';
          message.error(detail);
      } finally {
          setKnowledgeImportLoading(false);
      }
  };

  const handleFetchScriptHeaders = async () => {
      const values = scriptImportForm.getFieldsValue();
      const token = values.token;
      const dsId = values.data_source_id;
      if (!token || !dsId) {
          message.warning('请先选择数据源并填写表格地址或 Token');
          return;
      }
      setScriptImportLoading(true);
      try {
          const { cleanToken, importType, tableId, viewId } = parseFeishuInput(token);
          if (importType === 'docx') {
              message.info('文档类型无需解析列名');
              setScriptImportLoading(false);
              return;
          }
          if (importType === "bitable" && !tableId) {
              message.error('多维表格链接需要包含 table=xxx');
              return;
          }
          const res = await dataSourceApi.getFeishuHeaders(cleanToken, "", importType, tableId, dsId, viewId);
          const headers = res.data?.headers || [];
          setScriptImportHeaders(headers);
          if (headers.length > 0) {
              const titleField = values.title_field || headers[0];
              const contentFields = values.content_fields && values.content_fields.length > 0
                  ? values.content_fields
                  : headers.filter((h: string) => h !== titleField);
              scriptImportForm.setFieldsValue({
                  title_field: titleField,
                  content_fields: contentFields
              });
          }
      } catch (error) {
          message.error('解析列名失败');
      } finally {
          setScriptImportLoading(false);
      }
  };

  const handleImportScriptFromSource = async (values: any) => {
      const token = values.token;
      const dsId = values.data_source_id;
      if (!token || !dsId) {
          message.warning('请先选择数据源并填写表格地址或 Token');
          return;
      }
      setScriptImportLoading(true);
      try {
          const { cleanToken, importType, tableId, viewId } = parseFeishuInput(token);
          if (importType === "bitable" && !tableId) {
              message.error('多维表格链接需要包含 table=xxx');
              return;
          }
          const res = await scriptApi.importFeishu({
              spreadsheet_token: cleanToken,
              range_name: "",
              import_type: importType,
              table_id: tableId,
              view_id: viewId,
              data_source_id: dsId,
              category: values.category || 'sales_script',
              title_field: values.title_field || null,
              content_fields: values.content_fields || [],
              use_ai_processing: values.use_ai_processing
          });
          const imported = res.data?.imported ?? 0;
          const skipped = res.data?.skipped ?? 0;
          message.success(`导入完成：成功 ${imported} 条，跳过 ${skipped} 条`);
          setIsScriptImportModalOpen(false);
          scriptImportForm.resetFields();
          setScriptImportHeaders([]);
          loadScripts();
      } catch (error) {
          const detail = (error as any)?.response?.data?.detail || '导入失败';
          message.error(detail);
      } finally {
          setScriptImportLoading(false);
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
      // Helper to extract file object safely
      const getFile = (val: any) => {
          if (Array.isArray(val)) return val[0]?.originFileObj;
          if (val?.fileList && Array.isArray(val.fileList)) return val.fileList[0]?.originFileObj;
          return null;
      };

      try {
          if (knowledgeMode === 'script') {
              const formData = new FormData();
              formData.append('title', values.title);
              formData.append('category', values.category || 'sales_script');
              // use_ai_processing for script
              formData.append('use_ai_processing', values.use_ai_processing === undefined ? 'true' : String(values.use_ai_processing));

              const fileObj = getFile(values.file);
              if (fileObj) {
                  formData.append('file', fileObj);
              }
              const editingId = (form as any).__editingId;
              if (editingId) {
                  await scriptApi.updateScript(editingId, formData);
                  message.success('话术已更新');
              } else {
                  if (!fileObj) {
                      message.error('请上传话术文件');
                      return;
                  }
                  await scriptApi.uploadScript(formData);
                  message.success('话术已添加');
              }
              setIsKnowledgeModalOpen(false);
              knowledgeForm.resetFields();
              (form as any).__editingId = undefined;
              await loadScripts();
              return;
          }

          const formData = new FormData();
          formData.append('title', values.title);
          formData.append('category', values.category || 'general');
          // Fix: Ensure use_ai_processing is sent as string 'true' or 'false'
          formData.append('use_ai_processing', values.use_ai_processing === undefined ? 'true' : String(values.use_ai_processing));
          
          const fileObj = getFile(values.file);
          if (fileObj) {
              formData.append('file', fileObj);
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

  const handleViewScript = (record: any) => {
      scriptApi.getScript(record.id).then((res) => {
          setViewDoc(res.data);
          setIsViewModalOpen(true);
      }).catch(() => {
          setViewDoc(record);
          setIsViewModalOpen(true);
      });
  };

  const handleEditScript = (record: any) => {
      setKnowledgeMode('script');
      knowledgeForm.setFieldsValue({
          title: record.title,
          category: record.category
      });
      (form as any).__editingId = record.id;
      setIsKnowledgeModalOpen(true);
  };

  const handleDeleteScript = async (id: number) => {
      try {
          await scriptApi.deleteScript(id);
          message.success('话术已删除');
          await loadScripts();
      } catch (error) {
          message.error('删除失败');
      }
  };

  const handleEditKnowledge = (record: any) => {
      setKnowledgeMode('knowledge');
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

  const expandedRowRenderWithExcel = (record: any) => {
      if (record.source_type === 'feishu') {
          const saved = savedTokens[record.id] || [];
          return <FeishuRowDetail record={record} saved={saved} onSync={handleFeishuImport} onRemove={removeToken} importing={importing} />;
      }
      return null;
  };

  const skillColumns = [
      { title: '系统功能', dataIndex: 'name', key: 'name', render: (text: string) => <span className="font-bold">{text}</span> },
      { title: '功能描述', dataIndex: 'description', key: 'description' },
      { 
          title: '指定执行 LLM', 
          key: 'llm',
          render: (_: any, record: any) => {
                const mapping = skillMappings.find((m: any) => m.skill_name === record.key);
                const currentConfigId = mapping ? mapping.llm_config_id : undefined;
                
                return (
                  <Select 
                    style={{ width: 200 }} 
                    placeholder="默认" 
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
      { title: '标题', dataIndex: 'title', key: 'title', render: (text: string) => <span className="font-bold">{text}</span> },
      { title: '分类', dataIndex: 'category', key: 'category', render: (text: string) => <Tag>{text}</Tag> },
      { 
          title: '来源', 
          dataIndex: 'source', 
          key: 'source',
          render: (text: string) => {
              if (text && text.startsWith('feishu:')) return <Tag color="blue">飞书</Tag>;
              if (text && text.startsWith('manual')) return <Tag color="green">手动输入</Tag>;
              return <Tag color="purple">文件</Tag>;
          }
      },
      { title: '添加时间', dataIndex: 'created_at', key: 'created_at', render: (text: string) => formatDateTime(text) },
      { 
          title: '预处理状态', 
          key: 'status',
          render: (_: any, record: any) => {
              // Simple heuristic: if raw_content exists and is different from content, AI processing likely happened
              // Or check if content starts with markdown headers #
              const isProcessed = record.content && (record.content.startsWith('#') || record.content.includes('**核心摘要**'));
              return isProcessed ? (
                  <Tooltip title="AI 已进行结构化清洗与摘要">
                      <Tag color="success" icon={<RobotOutlined />}>AI 已优化</Tag>
                  </Tooltip>
              ) : (
                  <Tag color="default">原始内容</Tag>
              );
          }
      },
      { 
          title: '操作', 
          key: 'action', 
          render: (_: any, record: any) => (
              <div className="flex gap-2">
                  <Button type="text" icon={<ReadOutlined />} onClick={() => handleViewKnowledge(record)} />
                  <Button type="text" icon={<EditOutlined />} onClick={() => handleEditKnowledge(record)} />
                  <Popconfirm title="确定删除吗?" onConfirm={() => handleDeleteKnowledge(record.id)}>
                      <Button type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
              </div>
          ) 
      },
  ];

  const scriptColumns = [
      { title: '标题', dataIndex: 'title', key: 'title', render: (text: string) => <span className="font-bold">{text}</span> },
      { title: '分类', dataIndex: 'category', key: 'category', render: (text: string) => <Tag color="orange">{text}</Tag> },
      { 
          title: 'AI 优化', 
          key: 'ai_status',
          render: (_: any, record: any) => {
              const isOptimized = record.content && (record.content.includes('### Q:') || record.content.includes('**核心卖点**'));
              return isOptimized ? (
                  <Tooltip title="已提取问答对与卖点">
                      <Tag color="success" icon={<RobotOutlined />}>AI 已优化</Tag>
                  </Tooltip>
              ) : <Tag color="default">原始内容</Tag>;
          }
      },
      { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', render: (text: string) => formatDateTime(text) },
      { 
          title: '操作', 
          key: 'action', 
          render: (_: any, record: any) => (
              <div className="flex gap-2">
                  <Button type="text" icon={<ReadOutlined />} onClick={() => handleViewScript(record)} />
                  <Button type="text" icon={<EditOutlined />} onClick={() => handleEditScript(record)} />
                  <Popconfirm title="确定删除吗?" onConfirm={() => handleDeleteScript(record.id)}>
                      <Button type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
              </div>
          ) 
      },
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
      label: <span><DatabaseOutlined />客户数据源接入</span>,
      children: (
        <>
            <div className="mb-4 flex justify-between items-center">
                <h2 className="text-lg font-bold">客户数据源</h2>
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
      key: 'salesTalk',
      label: <span><ReadOutlined />话术库</span>,
      children: (
        <>
          <div className="mb-4 flex justify-between items-center">
            <h2 className="text-lg font-bold">话术库管理</h2>
            <div className="flex items-center gap-2">
              <Button onClick={() => {
                scriptImportForm.resetFields();
                setScriptImportHeaders([]);
                setIsScriptImportModalOpen(true);
              }}>从数据源导入</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => {
                setKnowledgeMode('script');
                setIsKnowledgeModalOpen(true);
                knowledgeForm.resetFields();
                knowledgeForm.setFieldsValue({ category: 'sales_script' });
                (form as any).__editingId = undefined;
              }}>添加话术脚本</Button>
            </div>
          </div>
          <Table 
            columns={scriptColumns} 
            dataSource={scripts} 
            rowKey="id" 
            loading={scriptsLoading} 
          />
        </>
      )
    },
    {
      key: 'knowledgeBase',
      label: <span><ReadOutlined />知识库</span>,
      children: (
        <>
          <div className="mb-4 flex justify-between items-center">
            <h2 className="text-lg font-bold">知识库管理</h2>
            <div className="flex items-center gap-2">
              <Button onClick={() => {
                knowledgeImportForm.resetFields();
                setKnowledgeImportHeaders([]);
                setIsKnowledgeImportModalOpen(true);
              }}>从数据源导入</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => {
                setKnowledgeMode('knowledge');
                setIsKnowledgeModalOpen(true);
                knowledgeForm.resetFields();
                knowledgeForm.setFieldsValue({ category: 'general' });
                (form as any).__editingId = undefined;
              }}>添加文档</Button>
            </div>
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
      label: <span><RobotOutlined />技能路由配置</span>,
      children: (
        <>
            <div className="mb-8">
                <h3 className="text-md font-bold mb-4">系统技能路由矩阵</h3>
                <div className="bg-blue-50 p-4 rounded-lg mb-4 text-sm text-blue-700">
                    <QuestionCircleOutlined /> 配置每个系统核心功能（Skill）使用哪个 LLM 模型执行。
                    例如：简单的闲聊可以使用便宜的模型 (gpt-3.5)，而复杂的画像生成可以使用强大的模型 (gpt-4)。
                </div>
                <Table columns={skillColumns} dataSource={SYSTEM_SKILLS} pagination={false} rowKey="key" />
            </div>

            <div>
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-md font-bold">关键词触发规则</h3>
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
              <Option value="openai_compatible">OpenAI Compatible (LiteLLM/Proxy)</Option>
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
        title={knowledgeMode === 'script' ? ((form as any).__editingId ? "编辑话术脚本" : "添加话术脚本") : ((form as any).__editingId ? "编辑文档" : "添加文档")} 
        open={isKnowledgeModalOpen} 
        onOk={() => knowledgeForm.submit()} 
        onCancel={() => setIsKnowledgeModalOpen(false)}
      >
        <Form form={knowledgeForm} layout="vertical" onFinish={handleAddKnowledge}>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder={knowledgeMode === 'script' ? "例如: 高净值客户话术 V1" : "例如: 资产配置知识摘要"} />
          </Form.Item>
          {knowledgeMode === 'script' ? (
              <Form.Item name="category" label="分类" initialValue="sales_script" hidden>
                  <Input />
              </Form.Item>
          ) : (
              <Form.Item name="category" label="分类" initialValue="general">
                 <Select>
                     <Option value="general">通用知识</Option>
                     <Option value="product_info">产品资料</Option>
                     <Option value="competitor">竞品分析</Option>
                 </Select>
              </Form.Item>
          )}
          
          {knowledgeMode === 'script' ? (
              <>
                <Form.Item name="file" label="上传话术文件" valuePropName="file" getValueFromEvent={(e) => e && e.fileList ? e.fileList : []}>
                    <Upload maxCount={1} beforeUpload={() => false}>
                        <Button icon={<UploadOutlined />}>选择文件</Button>
                    </Upload>
                </Form.Item>
                <Form.Item name="use_ai_processing" valuePropName="checked" initialValue={true}>
                    <Checkbox>启用 AI 话术预处理</Checkbox>
                    <div className="text-xs text-gray-500 ml-6">
                        自动提取话术问答对、关键卖点并优化结构。
                    </div>
                </Form.Item>
              </>
          ) : (
            <Tabs 
              defaultActiveKey="text"
              destroyInactiveTabPane
              items={[
                  {
                      key: 'text',
                      label: '手动输入',
                      children: (
                          <>
                              <Form.Item name="content" label="内容">
                                  <TextArea rows={10} placeholder="输入文档内容或话术..." />
                              </Form.Item>
                              <Form.Item name="use_ai_processing" valuePropName="checked" initialValue={true}>
                                  <Checkbox>启用 AI 知识预处理</Checkbox>
                              </Form.Item>
                          </>
                      )
                  },
                  {
                      key: 'file',
                      label: '文件上传',
                      children: (
                          <>
                            <Form.Item name="file" label="支持 PDF/Word/Excel/TXT/图片" valuePropName="file" getValueFromEvent={(e) => e && e.fileList ? e.fileList : []}>
                                <Upload maxCount={1} beforeUpload={() => false} accept=".pdf,.doc,.docx,.xlsx,.xls,.csv,.txt,.md,image/*">
                                    <Button icon={<UploadOutlined />}>选择文件</Button>
                                </Upload>
                            </Form.Item>
                            <Form.Item name="use_ai_processing" valuePropName="checked" initialValue={true}>
                                <Checkbox>启用 AI 知识预处理</Checkbox>
                                <div className="text-xs text-gray-500 ml-6">
                                    自动清洗文档格式、生成摘要并优化内容结构。
                                </div>
                            </Form.Item>
                          </>
                      )
                  }
              ]}
            />
          )}
        </Form>
      </Modal>

      <Modal 
        title="知识库从数据源导入"
        open={isKnowledgeImportModalOpen}
        onOk={() => knowledgeImportForm.submit()}
        onCancel={() => setIsKnowledgeImportModalOpen(false)}
        confirmLoading={knowledgeImportLoading}
      >
        <Form form={knowledgeImportForm} layout="vertical" onFinish={handleImportKnowledgeFromSource}>
          <Form.Item name="data_source_id" label="数据源" rules={[{ required: true }]}>
            <Select placeholder="选择飞书数据源">
              {(dataSources || []).filter((d: any) => d.source_type === 'feishu').map((ds: any) => (
                <Option key={ds.id} value={ds.id}>{ds.name}</Option>
              ))}
            </Select>
          </Form.Item>
          {(dataSources || []).filter((d: any) => d.source_type === 'feishu').length === 0 && (
              <div className="mb-4 text-sm text-yellow-600 bg-yellow-50 p-2 rounded">
                  还没有配置飞书数据源？请先去 <a onClick={() => { setIsKnowledgeImportModalOpen(false); }}>客户数据源接入</a> 页面配置 App ID 和 Secret。
              </div>
          )}
          <Form.Item name="token" label="文档地址或 Token" rules={[{ required: true }]}>
            <Input placeholder="支持飞书文档(Docx)、表格或多维表格链接" />
          </Form.Item>
          <Form.Item name="use_ai_processing" valuePropName="checked" initialValue={true}>
              <Checkbox>启用 AI 知识预处理 (推荐)</Checkbox>
              <div className="text-xs text-gray-500 ml-6">
                  LLM 将自动清洗文档格式、生成摘要并优化内容结构，提升检索效果。
              </div>
          </Form.Item>
          <Form.Item name="category" label="分类" initialValue="general">
             <Select>
             <Option value="general">通用知识</Option>
             <Option value="product_info">产品资料</Option>
             <Option value="competitor">竞品分析</Option>
             </Select>
          </Form.Item>
          <div className="flex items-center gap-2 mb-3">
            <Button onClick={handleFetchKnowledgeHeaders} loading={knowledgeImportLoading}>解析列名 (仅表格)</Button>
            {knowledgeImportHeaders.length > 0 && <span className="text-xs text-gray-500">已解析 {knowledgeImportHeaders.length} 列</span>}
          </div>
          <Form.Item name="title_field" label="标题字段 (仅表格)">
            <Select placeholder="选择标题列" allowClear options={knowledgeImportHeaders.map((h) => ({ label: h, value: h }))} />
          </Form.Item>
          <Form.Item name="content_fields" label="内容字段 (仅表格)">
            <Select mode="multiple" placeholder="选择内容列" options={knowledgeImportHeaders.map((h) => ({ label: h, value: h }))} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal 
        title="话术库从数据源导入"
        open={isScriptImportModalOpen}
        onOk={() => scriptImportForm.submit()}
        onCancel={() => setIsScriptImportModalOpen(false)}
        confirmLoading={scriptImportLoading}
      >
        <Form form={scriptImportForm} layout="vertical" onFinish={handleImportScriptFromSource}>
          <Form.Item name="data_source_id" label="数据源" rules={[{ required: true }]}>
            <Select placeholder="选择飞书数据源">
              {(dataSources || []).filter((d: any) => d.source_type === 'feishu').map((ds: any) => (
                <Option key={ds.id} value={ds.id}>{ds.name}</Option>
              ))}
            </Select>
          </Form.Item>
          {(dataSources || []).filter((d: any) => d.source_type === 'feishu').length === 0 && (
              <div className="mb-4 text-sm text-yellow-600 bg-yellow-50 p-2 rounded">
                  还没有配置飞书数据源？请先去 <a onClick={() => { setIsScriptImportModalOpen(false); }}>客户数据源接入</a> 页面配置 App ID 和 Secret。
              </div>
          )}
          <Form.Item name="token" label="文档地址或 Token" rules={[{ required: true }]}>
            <Input placeholder="支持飞书文档(Docx)、表格或多维表格链接" />
          </Form.Item>
          <Form.Item name="use_ai_processing" valuePropName="checked" initialValue={true}>
              <Checkbox>启用 AI 知识预处理 (推荐)</Checkbox>
              <div className="text-xs text-gray-500 ml-6">
                  LLM 将自动清洗文档格式、生成摘要并优化内容结构，提升检索效果。
              </div>
          </Form.Item>
          <Form.Item name="category" label="分类" initialValue="sales_script" hidden>
             <Input />
          </Form.Item>
          <div className="flex items-center gap-2 mb-3">
            <Button onClick={handleFetchScriptHeaders} loading={scriptImportLoading}>解析列名 (仅表格)</Button>
            {scriptImportHeaders.length > 0 && <span className="text-xs text-gray-500">已解析 {scriptImportHeaders.length} 列</span>}
          </div>
          <Form.Item name="title_field" label="标题字段 (仅表格)">
            <Select placeholder="选择标题列" allowClear options={scriptImportHeaders.map((h) => ({ label: h, value: h }))} />
          </Form.Item>
          <Form.Item name="content_fields" label="内容字段 (仅表格)">
            <Select mode="multiple" placeholder="选择内容列" options={scriptImportHeaders.map((h) => ({ label: h, value: h }))} />
          </Form.Item>
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
          <div className="mb-4 flex flex-wrap items-center gap-2">
              {viewDoc?.category && <Tag color="blue">{viewDoc?.category}</Tag>}
              {viewDoc?.source && <span className="text-gray-500">来源: {viewDoc?.source}</span>}
              {viewDoc?.filename && <span className="text-gray-500">文件: {viewDoc?.filename}</span>}
              {(viewDoc?.updated_at || viewDoc?.created_at) && (
                  <span className="text-gray-500">
                      {viewDoc?.updated_at ? '更新时间' : '添加时间'}: {formatDateTime(viewDoc?.updated_at || viewDoc?.created_at)}
                  </span>
              )}
          </div>
          
          <Tabs 
            items={[
                {
                    key: 'processed',
                    label: '处理后内容',
                    children: (
                        <div className="p-4 bg-gray-50 rounded-lg max-h-[60vh] overflow-y-auto whitespace-pre-wrap">
                            {viewDoc?.content || <span className="text-gray-400">暂无内容</span>}
                        </div>
                    )
                },
                {
                    key: 'raw',
                    label: '原始内容',
                    children: (
                        <div className="p-4 bg-gray-50 rounded-lg max-h-[60vh] overflow-y-auto whitespace-pre-wrap font-mono text-sm">
                            {viewDoc?.raw_content || <span className="text-gray-400">暂无原始内容</span>}
                        </div>
                    )
                }
            ]}
          />
      </Modal>
    </div>
  );
};

export default Settings;
