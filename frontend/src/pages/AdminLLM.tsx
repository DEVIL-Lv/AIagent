import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Input, Select, Switch, message, Tag, Card } from 'antd';
import { PlusOutlined, EditOutlined, ApiOutlined } from '@ant-design/icons';
import { llmApi } from '../services/api';
import { useNavigate } from 'react-router-dom';

const { Option } = Select;

const AdminLLM: React.FC = () => {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();

  useEffect(() => {
    loadConfigs();
  }, []);

  const loadConfigs = async () => {
    try {
      const res = await llmApi.getConfigs();
      setConfigs(res.data);
    } catch (error) {
      message.error("加载配置失败");
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (values: any) => {
    try {
      await llmApi.createConfig(values);
      message.success("添加成功");
      setIsModalVisible(false);
      form.resetFields();
      loadConfigs();
    } catch (error) {
      message.error("添加失败");
    }
  };

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', render: (text: string) => <b>{text}</b> },
    { title: '提供商', dataIndex: 'provider', key: 'provider', render: (text: string) => <Tag color="blue">{text}</Tag> },
    { title: '模型', dataIndex: 'model_name', key: 'model_name' },
    { title: '状态', dataIndex: 'is_active', key: 'is_active', render: (active: boolean) => active ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag> },
  ];

  return (
    <div className="p-8 bg-gray-50 min-h-screen">
       <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold flex items-center gap-2"><ApiOutlined /> LLM 模型管理</h2>
        <Button onClick={() => navigate('/')}>返回看板</Button>
      </div>

      <Card>
        <div className="mb-4">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalVisible(true)}>
            添加新模型
          </Button>
        </div>
        <Table dataSource={configs} columns={columns} rowKey="id" loading={loading} />
      </Card>

      <Modal
        title="添加 LLM 配置"
        open={isModalVisible}
        onCancel={() => setIsModalVisible(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate} initialValues={{ provider: 'openai', temperature: 0.7, is_active: true }}>
          <Form.Item name="name" label="配置名称 (如: GPT-4生产环境)" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select>
              <Option value="openai">OpenAI</Option>
              <Option value="anthropic">Anthropic (Claude)</Option>
              <Option value="azure">Azure OpenAI</Option>
            </Select>
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="model_name" label="模型代码 (如: gpt-4-turbo, claude-3-opus)" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="api_base" label="API Base URL (可选，用于中转/DeepSeek)">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item name="temperature" label="随机性 (Temperature)">
             <Input type="number" step={0.1} min={0} max={1} />
          </Form.Item>
          <Form.Item name="is_active" label="是否启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default AdminLLM;
