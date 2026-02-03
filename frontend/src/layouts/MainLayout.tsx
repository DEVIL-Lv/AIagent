import React from 'react';
import { Layout, Menu, Avatar } from 'antd';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { 
  UserOutlined, 
  BarChartOutlined, 
  SettingOutlined, 
  RobotOutlined
} from '@ant-design/icons';

const { Header, Content } = Layout;

const MainLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    {
      key: '/dashboard',
      icon: <UserOutlined />,
      label: '客户管理',
      onClick: () => navigate('/dashboard'),
    },
    {
      key: '/analysis',
      icon: <BarChartOutlined />,
      label: '数据分析',
      onClick: () => navigate('/analysis'),
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '系统设置',
      onClick: () => navigate('/settings'),
    },
  ];



  return (
    <Layout className="min-h-screen bg-gray-50">
      <Header className="bg-white px-8 h-16 border-b border-gray-200 flex justify-between items-center sticky top-0 z-50 shadow-sm">
          <div className="flex items-center gap-3 text-blue-600 font-bold text-xl mr-8">
              <div className="bg-blue-50 p-1.5 rounded-lg">
                <RobotOutlined className="text-2xl" />
              </div>
              <span>AI CRM</span>
          </div>

          <div className="flex-1">
            <Menu
              theme="light"
              mode="horizontal"
              selectedKeys={[location.pathname]}
              items={menuItems}
              className="border-none text-base font-medium min-w-[400px]"
              style={{ background: 'transparent', lineHeight: '62px' }}
            />
          </div>
          
          <div className="flex items-center gap-4">
             <div className="hidden md:flex items-center text-xs text-gray-400 bg-gray-50 px-3 py-1 rounded-full border border-gray-100">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500 mr-2 animate-pulse"></span>
                v4.0.0 Stable
             </div>
             
             <div className="flex items-center gap-2 pl-2 pr-4 py-1.5 rounded-full transition-all border border-transparent">
                <Avatar 
                    style={{ backgroundColor: '#1890ff' }} 
                    icon={<UserOutlined />} 
                    size="small"
                />
                <span className="font-medium text-gray-700 text-sm">Administrator</span>
             </div>
          </div>
      </Header>
      
      <Content className="p-6 h-[calc(100vh-64px)] overflow-hidden max-w-[1920px] mx-auto w-full">
        <Outlet />
      </Content>
    </Layout>
  );
};

export default MainLayout;

