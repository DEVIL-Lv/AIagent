import React, { useState, useEffect } from 'react';
import { Button, Popover, List, Typography, Popconfirm, Spin, message, Tooltip } from 'antd';
import { PlusOutlined, HistoryOutlined, DeleteOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { sessionApi } from '../services/api';

const { Text } = Typography;

interface ChatSession {
    id: number;
    title: string;
    updated_at: string;
}

interface SessionHeaderProps {
    customerId?: number; // If undefined, it's global chat
    currentSessionId: number | null;
    onSessionChange: (sessionId: number | null) => void;
    onNewChat: () => void;
}

const SessionHeader: React.FC<SessionHeaderProps> = ({ 
    customerId, 
    currentSessionId, 
    onSessionChange, 
    onNewChat 
}) => {
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [loading, setLoading] = useState(false);
    const [popoverOpen, setPopoverOpen] = useState(false);

    const loadSessions = async () => {
        setLoading(true);
        try {
            const res = await sessionApi.getSessions(customerId);
            setSessions(res.data);
        } catch (error) {
            message.error("加载历史会话失败");
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (e: React.MouseEvent, id: number) => {
        e.stopPropagation();
        try {
            await sessionApi.deleteSession(id);
            setSessions(prev => prev.filter(s => s.id !== id));
            if (currentSessionId === id) {
                onSessionChange(null);
                onNewChat();
            }
            message.success("删除成功");
        } catch (error) {
            message.error("删除失败");
        }
    };

    const handleSelect = (id: number) => {
        onSessionChange(id);
        setPopoverOpen(false);
    };

    const handleOpenChange = (newOpen: boolean) => {
        setPopoverOpen(newOpen);
        if (newOpen) {
            loadSessions();
        }
    };

    const content = (
        <div className="w-64 max-h-80 overflow-y-auto custom-scrollbar">
            {loading ? (
                <div className="text-center py-4"><Spin size="small" /></div>
            ) : sessions.length === 0 ? (
                <div className="text-center py-4 text-gray-400 text-xs">暂无历史会话</div>
            ) : (
                <List
                    size="small"
                    dataSource={sessions}
                    renderItem={item => (
                        <List.Item 
                            className={`cursor-pointer hover:bg-gray-50 transition-colors group px-2 py-2 rounded-md ${currentSessionId === item.id ? 'bg-blue-50' : ''}`}
                            onClick={() => handleSelect(item.id)}
                        >
                            <div className="flex justify-between items-center w-full">
                                <div className="flex flex-col overflow-hidden">
                                    <Text className={`truncate text-sm ${currentSessionId === item.id ? 'text-blue-600 font-medium' : 'text-gray-700'}`}>
                                        {item.title || "新对话"}
                                    </Text>
                                    <Text type="secondary" className="text-xs">
                                        {new Date(item.updated_at).toLocaleDateString()}
                                    </Text>
                                </div>
                                <div className="flex items-center gap-1">
                                    {currentSessionId === item.id && <CheckCircleOutlined className="text-blue-500 text-xs" />}
                                    <Popconfirm
                                        title="确定删除此会话？"
                                        onConfirm={(e) => handleDelete(e as any, item.id)}
                                        onCancel={(e) => e?.stopPropagation()}
                                        okText="删除"
                                        cancelText="取消"
                                    >
                                        <Button 
                                            type="text" 
                                            size="small" 
                                            icon={<DeleteOutlined />} 
                                            className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500"
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    </Popconfirm>
                                </div>
                            </div>
                        </List.Item>
                    )}
                />
            )}
        </div>
    );

    return (
        <div className="flex items-center gap-1 bg-gray-100 p-0.5 rounded-lg">
            <Tooltip title="开启新对话">
                <Button 
                    type="text" 
                    size="small" 
                    icon={<PlusOutlined />} 
                    onClick={onNewChat}
                    className="text-gray-600 hover:text-blue-600 hover:bg-white rounded-md"
                >
                    新对话
                </Button>
            </Tooltip>
            <div className="w-px h-4 bg-gray-300 mx-1"></div>
            <Popover
                content={content}
                title="历史会话"
                trigger="click"
                open={popoverOpen}
                onOpenChange={handleOpenChange}
                placement="bottomRight"
                overlayClassName="session-history-popover"
            >
                <Tooltip title="历史会话">
                    <Button 
                        type="text" 
                        size="small" 
                        icon={<HistoryOutlined />} 
                        className={`text-gray-600 hover:text-blue-600 hover:bg-white rounded-md ${popoverOpen ? 'bg-white text-blue-600' : ''}`}
                    >
                        历史
                    </Button>
                </Tooltip>
            </Popover>
        </div>
    );
};

export default SessionHeader;
