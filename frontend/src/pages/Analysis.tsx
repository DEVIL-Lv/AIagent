import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Spin } from 'antd';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { UserOutlined, RiseOutlined, CheckCircleOutlined, TeamOutlined } from '@ant-design/icons';
import { analysisApi } from '../services/api';

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

const Analysis: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const res = await analysisApi.getStats();
      setData(res.data);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="p-20 text-center"><Spin size="large" /></div>;

  return (
    <div className="p-6 h-full overflow-y-auto">
      <h2 className="text-2xl font-bold text-gray-700 mb-6">数据分析大屏</h2>
      
      {/* Key Metrics */}
      <Row gutter={16} className="mb-8">
        <Col span={6}>
          <Card variant="borderless" className="shadow-sm rounded-xl">
            <Statistic 
              title="总客户数" 
              value={data?.metrics.total} 
              prefix={<TeamOutlined className="text-blue-500"/>} 
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card variant="borderless" className="shadow-sm rounded-xl">
            <Statistic 
              title="高意向客户" 
              value={data?.metrics.high_intent} 
              valueStyle={{ color: '#cf1322' }}
              prefix={<RiseOutlined />} 
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card variant="borderless" className="shadow-sm rounded-xl">
            <Statistic 
              title="已成交" 
              value={data?.metrics.closed} 
              valueStyle={{ color: '#3f8600' }}
              prefix={<CheckCircleOutlined />} 
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card variant="borderless" className="shadow-sm rounded-xl">
            <Statistic 
              title="本周活跃" 
              value={data?.metrics.active_weekly} 
              prefix={<UserOutlined />} 
            />
          </Card>
        </Col>
      </Row>

      {/* Charts */}
      <Row gutter={24}>
        <Col span={12}>
          <Card title="销售漏斗 (转化阶段)" variant="borderless" className="shadow-sm rounded-xl h-[400px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={data?.funnel}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="stage" type="category" width={80} />
                <RechartsTooltip />
                <Legend />
                <Bar dataKey="count" name="客户数量" fill="#1890ff" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="风险偏好分布" variant="borderless" className="shadow-sm rounded-xl h-[400px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data?.risk}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => {
                    const p = percent ?? 0;
                    return `${name}: ${(p * 100).toFixed(0)}%`;
                  }}
                  outerRadius={120}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {data?.risk.map((entry: any, index: number) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <RechartsTooltip />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Analysis;
