import React, { useMemo, useState } from 'react';
import { Avatar, Collapse, Descriptions, Input, Select, Table, Tag, Typography } from 'antd';
import { RobotOutlined, UserOutlined } from '@ant-design/icons';

export type ChatMessage = {
  role: 'user' | 'ai';
  content: string;
  timestamp: string;
};

type Variant = 'agent' | 'customer' | 'global';

type ChatMessageListProps = {
  messages: ChatMessage[];
  variant: Variant;
  className?: string;
  containerRef?: React.RefObject<HTMLDivElement>;
  emptyState?: React.ReactNode;
};

type StructuredInfoTable = {
  name: string;
  headers: string[];
  rows: Record<string, string>[];
};

type StructuredInfo = {
  basic: Record<string, string>;
  tables: StructuredInfoTable[];
  archives: string[];
};

const parseTimestamp = (ts: string) => {
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(ts);
  const pure = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(ts);
  const target = !hasTz && pure ? `${ts}Z` : ts;
  return new Date(target);
};

const isStructuredInfoContent = (content: string) => {
  if (!content) return false;
  return (
    content.includes('【客户基本信息】') ||
    content.includes('【表格：') ||
    content.includes('【档案资料】')
  );
};

const normalizeCellValue = (value: string) =>
  value.replace(/\\\|/g, '|').replace(/<br\s*\/?>/gi, '\n').trim();

const splitPipeRow = (line: string) => line.split(' | ').map((v) => normalizeCellValue(v));

const parseKeyValueLine = (line: string): [string, string] | null => {
  const sep = line.includes('：') ? '：' : line.includes(':') ? ':' : null;
  if (!sep) return null;
  const idx = line.indexOf(sep);
  if (idx <= 0) return null;
  const key = line.slice(0, idx).trim();
  const value = line.slice(idx + 1).trim();
  if (!key) return null;
  return [key, value];
};

const parseStructuredInfo = (content: string): StructuredInfo | null => {
  if (!isStructuredInfoContent(content)) return null;

  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const basic: Record<string, string> = {};
  const tables: StructuredInfoTable[] = [];
  const archives: string[] = [];

  const isDelimiter = (s: string) => s.trim() === '----------------';
  const isSectionHeader = (s: string) =>
    s === '【客户基本信息】' || s === '【档案资料】' || (s.startsWith('【表格：') && s.endsWith('】'));

  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const line = (raw || '').trim();
    if (!line) {
      i += 1;
      continue;
    }

    if (line === '【客户基本信息】') {
      i += 1;
      while (i < lines.length) {
        const l = (lines[i] || '').trim();
        if (!l) {
          i += 1;
          continue;
        }
        if (isDelimiter(l) || isSectionHeader(l)) break;
        const kv = parseKeyValueLine(l);
        if (kv) basic[kv[0]] = kv[1];
        i += 1;
      }
      continue;
    }

    if (line.startsWith('【表格：') && line.endsWith('】')) {
      const name = line.slice('【表格：'.length, -1).trim() || '表格';
      i += 1;
      while (i < lines.length && !(lines[i] || '').trim()) i += 1;
      const headerLine = ((lines[i] || '') as string).trim();
      const headers = headerLine.includes(' | ') ? splitPipeRow(headerLine) : [];

      i += 1;
      while (i < lines.length && !(lines[i] || '').trim()) i += 1;
      if (i < lines.length && ((lines[i] || '') as string).trim().includes('---')) i += 1;

      const rows: Record<string, string>[] = [];
      while (i < lines.length) {
        const l = (lines[i] || '').trim();
        if (!l) {
          i += 1;
          continue;
        }
        if (isDelimiter(l) || isSectionHeader(l)) break;
        if (headers.length > 0 && l.includes(' | ')) {
          const parts = splitPipeRow(l);
          const row: Record<string, string> = {};
          headers.forEach((h, idx) => {
            row[h] = parts[idx] ?? '';
          });
          rows.push(row);
        }
        i += 1;
      }

      tables.push({ name, headers, rows });
      continue;
    }

    if (line === '【档案资料】') {
      i += 1;
      while (i < lines.length) {
        const l = (lines[i] || '').trim();
        if (!l) {
          i += 1;
          continue;
        }
        if (isDelimiter(l) || isSectionHeader(l)) break;
        if (l.startsWith('- ')) archives.push(normalizeCellValue(l.slice(2)));
        i += 1;
      }
      continue;
    }

    i += 1;
  }

  if (Object.keys(basic).length === 0 && tables.length === 0 && archives.length === 0) return null;
  return { basic, tables, archives };
};

const getStageLabel = (stage: string) => {
  switch (stage) {
    case 'closing':
      return '商务谈判';
    case 'product_matching':
      return '需求分析';
    case 'trust_building':
      return '建立信任';
    case 'contact_before':
      return '待开发';
    default:
      return stage;
  }
};

const pickDefaultColumns = (headers: string[]) => {
  const preferred = [
    '姓名',
    '客户姓名',
    '手机',
    '手机号',
    '电话',
    '联系方式',
    '跟进人',
    '负责人',
    '创建时间',
    '更新时间',
    '行业',
    '客户行业',
    '微信',
    '微信昵称',
    'ID',
  ];
  const set = new Set(headers);
  const chosen: string[] = [];
  for (const k of preferred) {
    if (set.has(k)) chosen.push(k);
    if (chosen.length >= 6) break;
  }
  if (chosen.length >= 3) return chosen;
  return headers.slice(0, 6);
};

const StructuredTable: React.FC<{ table: StructuredInfoTable }> = ({ table }) => {
  const [selectedColumns, setSelectedColumns] = useState<string[]>(() => pickDefaultColumns(table.headers));
  const [searchText, setSearchText] = useState('');

  const safeColumns = selectedColumns.length > 0 ? selectedColumns : pickDefaultColumns(table.headers);

  const dataSource = useMemo(() => {
    const query = searchText.trim();
    const matches = (row: Record<string, string>) => {
      if (!query) return true;
      const q = query.toLowerCase();
      return safeColumns.some((c) => String(row[c] ?? '').toLowerCase().includes(q));
    };
    return table.rows
      .filter(matches)
      .map((row, idx) => ({
        key: `${table.name}-${idx}`,
        ...row,
      }));
  }, [safeColumns, searchText, table.name, table.rows]);

  const columns = useMemo(
    () =>
      safeColumns.map((h) => ({
        title: h,
        dataIndex: h,
        key: h,
        render: (value: any) => (
          <div className="whitespace-pre-wrap break-words text-xs text-gray-700">{String(value ?? '')}</div>
        ),
      })),
    [safeColumns],
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          mode="multiple"
          size="small"
          placeholder="选择字段"
          value={selectedColumns}
          onChange={(v) => setSelectedColumns(v)}
          style={{ minWidth: 200, maxWidth: 520 }}
          options={table.headers.map((h) => ({ label: h, value: h }))}
        />
        <Input
          size="small"
          placeholder="搜索（在已选字段内）"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{ width: 220 }}
        />
        <Tag color="blue">{dataSource.length} 行</Tag>
      </div>
      <div className="overflow-x-auto">
        <Table
          size="small"
          pagination={{ pageSize: 5, showSizeChanger: true, pageSizeOptions: [5, 10, 20] }}
          columns={columns as any}
          dataSource={dataSource}
          scroll={{ x: 'max-content' }}
        />
      </div>
    </div>
  );
};

const StructuredInfoMessage: React.FC<{ content: string }> = ({ content }) => {
  const parsed = useMemo(() => parseStructuredInfo(content), [content]);
  if (!parsed) return <div className="whitespace-pre-wrap">{content}</div>;

  const basicItems = Object.entries(parsed.basic);
  const hasBasic = basicItems.length > 0;
  const hasTables = parsed.tables.length > 0;
  const hasArchives = parsed.archives.length > 0;

  const basicRows = (
    <Descriptions size="small" column={1} className="text-xs">
      {basicItems.map(([k, v]) => {
        const value =
          k.includes('阶段') && v ? (
            <Tag color="gold">{getStageLabel(v)}</Tag>
          ) : k.includes('风险') && v ? (
            <Tag color="geekblue">{v}</Tag>
          ) : (
            <span className="text-xs text-gray-700 break-words">{v}</span>
          );
        return (
          <Descriptions.Item key={k} label={<span className="text-xs text-gray-500">{k}</span>}>
            {value}
          </Descriptions.Item>
        );
      })}
    </Descriptions>
  );

  const collapseItems = [
    ...(hasTables
      ? parsed.tables.map((t) => ({
          key: `table:${t.name}`,
          label: (
            <div className="flex items-center gap-2">
              <span className="font-medium">表格：{t.name}</span>
              <Tag color="blue">{t.rows.length} 行</Tag>
            </div>
          ),
          children: <StructuredTable table={t} />,
        }))
      : []),
    ...(hasArchives
      ? [
          {
            key: 'archives',
            label: (
              <div className="flex items-center gap-2">
                <span className="font-medium">档案资料</span>
                <Tag>{parsed.archives.length}</Tag>
              </div>
            ),
            children: (
              <div className="space-y-1">
                {parsed.archives.map((a, idx) => (
                  <Typography.Paragraph
                    key={`${idx}-${a.slice(0, 12)}`}
                    className="mb-1 text-xs text-gray-700 whitespace-pre-wrap"
                    ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                  >
                    {a}
                  </Typography.Paragraph>
                ))}
              </div>
            ),
          },
        ]
      : []),
    {
      key: 'raw',
      label: <span className="font-medium">查看原文</span>,
      children: <div className="whitespace-pre-wrap text-xs text-gray-600">{content}</div>,
    },
  ];

  return (
    <div className="space-y-2">
      {hasBasic && (
        <div>
          <div className="font-medium text-gray-800 mb-1">客户基本信息</div>
          {basicRows}
        </div>
      )}
      {(hasTables || hasArchives) && <Collapse size="small" items={collapseItems} />}
      {!hasTables && !hasArchives && !hasBasic && (
        <div className="whitespace-pre-wrap text-xs text-gray-600">{content}</div>
      )}
    </div>
  );
};

const renderAgentMessage = (msg: ChatMessage, idx: number) => (
  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
    <div
      className={`max-w-[80%] rounded-2xl p-4 shadow-sm ${
        msg.role === 'user'
          ? 'bg-purple-600 text-white rounded-br-none'
          : 'bg-white border border-gray-100 text-gray-800 rounded-bl-none'
      }`}
    >
      {msg.role === 'ai' ? <StructuredInfoMessage content={msg.content} /> : <div className="whitespace-pre-wrap">{msg.content}</div>}
      <div className={`text-xs mt-1.5 ${msg.role === 'user' ? 'text-purple-200' : 'text-gray-400'}`}>
        {parseTimestamp(msg.timestamp).toLocaleString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        })}
      </div>
    </div>
  </div>
);

const renderCustomerMessage = (msg: ChatMessage, idx: number) => (
  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
    <div className={`flex gap-3 max-w-[80%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
      <Avatar
        icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
        className={msg.role === 'user' ? 'bg-blue-500' : 'bg-green-500'}
      />
      <div
        className={`p-3 rounded-xl shadow-sm whitespace-pre-wrap ${
          msg.role === 'user'
            ? 'bg-blue-500 text-white rounded-tr-none'
            : 'bg-white border text-gray-700 rounded-tl-none'
        }`}
      >
        {msg.role === 'ai' ? <StructuredInfoMessage content={msg.content} /> : msg.content}
      </div>
    </div>
  </div>
);

const renderGlobalMessage = (msg: ChatMessage, idx: number) => (
  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in`}>
    <div className={`flex gap-2 max-w-[90%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
      <Avatar
        size="small"
        src={msg.role === 'ai' ? 'https://api.dicebear.com/7.x/bottts/svg?seed=ai' : undefined}
        icon={msg.role === 'user' ? <UserOutlined /> : undefined}
        className={msg.role === 'user' ? 'bg-blue-600 mt-0.5' : 'bg-transparent mt-0.5'}
      />
      <div>
        <div
          className={`px-3 py-2 rounded-xl text-sm whitespace-pre-wrap leading-relaxed ${
            msg.role === 'user'
              ? 'bg-blue-600 text-white rounded-tr-none'
              : 'bg-white border border-gray-100 text-gray-700 rounded-tl-none shadow-sm'
          }`}
        >
          {msg.role === 'ai' ? <StructuredInfoMessage content={msg.content} /> : msg.content}
        </div>
      </div>
    </div>
  </div>
);

const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  variant,
  className,
  containerRef,
  emptyState,
}) => {
  const renderMessage = (msg: ChatMessage, idx: number) => {
    if (variant === 'agent') return renderAgentMessage(msg, idx);
    if (variant === 'customer') return renderCustomerMessage(msg, idx);
    return renderGlobalMessage(msg, idx);
  };

  return (
    <div className={className} ref={containerRef}>
      {messages.length === 0 ? emptyState : messages.map(renderMessage)}
    </div>
  );
};

export default ChatMessageList;
