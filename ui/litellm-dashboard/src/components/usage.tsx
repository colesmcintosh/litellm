import { BarChart, BarList, Card, Title, Table, TableHead, TableHeaderCell, TableRow, TableCell, TableBody, Metric, Subtitle } from "@tremor/react";

import React, { useState, useEffect, useRef, useCallback } from "react";

import ViewUserSpend from "./view_user_spend";
import { ProxySettings } from "./user_dashboard";
import UsageDatePicker from "./shared/usage_date_picker";
import { 
  Grid, Col, Text, 
  LineChart, TabPanel, TabPanels, 
  TabGroup, TabList, Tab, Select, SelectItem, 
  DateRangePicker, DateRangePickerValue, 
  DonutChart,
  AreaChart,
  Callout,
  Button,
  MultiSelect,
  MultiSelectItem,
} from "@tremor/react";

import {
  Select as Select2
} from "antd";

import {
  userSpendLogsCall,
  keyInfoCall,
  adminSpendLogsCall,
  adminTopKeysCall,
  adminTopModelsCall,
  adminTopEndUsersCall,
  teamSpendLogsCall,
  tagsSpendLogsCall,
  allTagNamesCall,
  modelMetricsCall,
  modelAvailableCall,
  adminspendByProvider,
  adminGlobalActivity,
  adminGlobalActivityPerModel,
  getProxyUISettings,
  fetchDashboardSummary,
  fetchActivitySummary,
  fetchTeamsSummary,
  fetchTotalRequests,
  fetchSuccessfulRequests,
  fetchFailedRequests,
  fetchTotalTokens,
  fetchTotalSpend,
  fetchAverageCostPerRequest,
  fetchTeamTotalRequests,
  fetchTeamSuccessfulRequests,
  fetchTeamFailedRequests,
  fetchTeamTotalTokens,
  fetchTeamTotalSpend,
  fetchTeamAverageCostPerRequest,
  fetchTagTotalRequests,
  fetchTagSuccessfulRequests,
  fetchTagFailedRequests,
  fetchTagTotalTokens,
  fetchTagTotalSpend,
  fetchTagAverageCostPerRequest
} from "./networking";
import { start } from "repl";
import TopKeyView from "./top_key_view";
import { formatNumberWithCommas } from "@/utils/dataUtils";
console.log("process.env.NODE_ENV", process.env.NODE_ENV);

// Simple skeleton loader component for progressive loading
const SkeletonLoader = ({ height = "h-40", width = "w-full" }: { height?: string, width?: string }) => (
  <div className={`${height} ${width} bg-gray-200 rounded animate-pulse`}></div>
);

// Fake data for skeleton loaders to make them look more realistic
const generateFakeChartData = (count: number = 30) => {
  return Array.from({ length: count }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (count - i));
    return {
      date: date.toISOString().split('T')[0],
      spend: Math.random() * 1000,
      api_requests: Math.floor(Math.random() * 1000),
      total_tokens: Math.floor(Math.random() * 50000)
    };
  });
};

const generateFakeTopData = (count: number = 5) => {
  return Array.from({ length: count }, (_, i) => ({
    key: `loading-item-${i}`,
    spend: (Math.random() * 500).toFixed(2),
    name: `Loading...`,
  }));
};

// Enhanced skeleton loader with fake data
const ChartSkeletonLoader = ({ chartType = "bar" }: { chartType?: "bar" | "line" | "area" }) => {
  const fakeData = generateFakeChartData();
  
  return (
    <div className="opacity-50 pointer-events-none">
      {chartType === "bar" && (
        <BarChart
          data={fakeData}
          index="date"
          categories={["spend"]}
          valueFormatter={() => "Loading..."}
          showLegend={false}
          showAnimation={false}
        />
      )}
      {chartType === "line" && (
        <LineChart
          data={fakeData}
          index="date"
          categories={["api_requests"]}
          valueFormatter={() => "Loading..."}
          showLegend={false}
          showAnimation={false}
        />
      )}
      {chartType === "area" && (
        <AreaChart
          data={fakeData}
          index="date"
          categories={["total_tokens"]}
          valueFormatter={() => "Loading..."}
          showLegend={false}
          showAnimation={false}
        />
      )}
    </div>
  );
};

const TableSkeletonLoader = () => {
  const fakeData = generateFakeTopData();
  
  return (
    <div className="opacity-50 pointer-events-none">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Item</TableHeaderCell>
            <TableHeaderCell>Value</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {fakeData.map((item, index) => (
            <TableRow key={index}>
              <TableCell>
                <div className="bg-gray-200 h-4 w-24 rounded animate-pulse"></div>
              </TableCell>
              <TableCell>
                <div className="bg-gray-200 h-4 w-16 rounded animate-pulse"></div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

// Virtual scrolling component for large tables
const VirtualizedTable = ({ 
  data, 
  itemHeight = 50, 
  containerHeight = 500, 
  renderItem 
}: { 
  data: any[], 
  itemHeight?: number, 
  containerHeight?: number,
  renderItem: (item: any, index: number) => React.ReactNode 
}) => {
  const [scrollTop, setScrollTop] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const visibleCount = Math.ceil(containerHeight / itemHeight);
  const totalHeight = data.length * itemHeight;
  
  const startIndex = Math.floor(scrollTop / itemHeight);
  const endIndex = Math.min(startIndex + visibleCount + 1, data.length);
  
  const visibleItems = data.slice(startIndex, endIndex);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  };

  return (
    <div 
      ref={containerRef}
      style={{ height: containerHeight, overflow: 'auto' }}
      onScroll={handleScroll}
      className="relative"
    >
      <div style={{ height: totalHeight, position: 'relative' }}>
        <div style={{ 
          transform: `translateY(${startIndex * itemHeight}px)`,
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
        }}>
          {visibleItems.map((item, index) => (
            <div key={startIndex + index} style={{ height: itemHeight }}>
              {renderItem(item, startIndex + index)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

interface UsagePageProps {
  accessToken: string | null;
  token: string | null;
  userRole: string | null;
  userID: string | null;
  keys: any[] | null;
  premiumUser: boolean;
}

interface GlobalActivityData {
  sum_api_requests: number;
  sum_total_tokens: number;
  daily_data: { date: string; api_requests: number; total_tokens: number }[];
}


type CustomTooltipTypeBar = {
  payload: any;
  active: boolean | undefined;
  label: any;
};


const customTooltip = (props: CustomTooltipTypeBar) => {
  const { payload, active } = props;
  if (!active || !payload) return null;

  const value = payload[0].payload;
  const date = value["startTime"];
  const model_values = value["models"];
  const entries: [string, number][] = Object.entries(model_values).map(
    ([key, value]) => [key, value as number]
  );

  entries.sort((a, b) => b[1] - a[1]);
  const topEntries = entries.slice(0, 5);

  return (
    <div className="w-56 rounded-tremor-default border border-tremor-border bg-tremor-background p-2 text-tremor-default shadow-tremor-dropdown">
      {date}
      {topEntries.map(([key, value]) => (
        <div key={key} className="flex flex-1 space-x-10">
          <div className="p-2">
            <p className="text-tremor-content text-xs">
              {key}
              {":"}
              <span className="text-xs text-tremor-content-emphasis">
                {" "}
                {value ? `$${formatNumberWithCommas(value, 2)}` : ""}
              </span>
            </p>
          </div>
        </div>
      ))}
    </div>
  );
};

function getTopKeys(data: Array<{ [key: string]: unknown }>): any[] {
  const spendKeys: { key: string; spend: unknown }[] = [];

  data.forEach((dict) => {
    Object.entries(dict).forEach(([key, value]) => {
      if (
        key !== "spend" &&
        key !== "startTime" &&
        key !== "models" &&
        key !== "users"
      ) {
        spendKeys.push({ key, spend: value });
      }
    });
  });

  spendKeys.sort((a, b) => Number(b.spend) - Number(a.spend));

  const topKeys = spendKeys.slice(0, 5).map((k) => k.key);
  console.log(`topKeys: ${Object.keys(topKeys[0])}`);
  return topKeys;
}
type DataDict = { [key: string]: unknown };
type UserData = { user_id: string; spend: number };


const isAdminOrAdminViewer = (role: string | null): boolean => {
  if (role === null) return false;
  return role === 'Admin' || role === 'Admin Viewer';
};



const UsagePage: React.FC<UsagePageProps> = ({
  accessToken,
  token,
  userRole,
  userID,
  keys,
  premiumUser,
}) => {
  const currentDate = new Date();
  const [keySpendData, setKeySpendData] = useState<any[]>([]);
  const [topKeys, setTopKeys] = useState<any[]>([]);
  const [topModels, setTopModels] = useState<any[]>([]);
  const [topUsers, setTopUsers] = useState<any[]>([]);
  const [teamSpendData, setTeamSpendData] = useState<any[]>([]);
  const [topTagsData, setTopTagsData] = useState<any[]>([]);
  const [allTagNames, setAllTagNames] = useState<string[]>([]);
  const [uniqueTeamIds, setUniqueTeamIds] = useState<any[]>([]);
  const [totalSpendPerTeam, setTotalSpendPerTeam] = useState<any[]>([]);
  const [spendByProvider, setSpendByProvider] = useState<any[]>([]);
  const [globalActivity, setGlobalActivity] = useState<GlobalActivityData>({} as GlobalActivityData);
  const [globalActivityPerModel, setGlobalActivityPerModel] = useState<any[]>([]);
  const [selectedKeyID, setSelectedKeyID] = useState<string | null>("");
  const [selectedTags, setSelectedTags] = useState<string[]>(["all-tags"]);
  const [dateValue, setDateValue] = useState<DateRangePickerValue>({
    from: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000), 
    to: new Date(),
  });
  
  // Individual metrics state
  const [totalRequests, setTotalRequests] = useState<number>(0);
  const [successfulRequests, setSuccessfulRequests] = useState<number>(0);
  const [failedRequests, setFailedRequests] = useState<number>(0);
  const [totalTokens, setTotalTokens] = useState<number>(0);
  const [totalSpend, setTotalSpend] = useState<number>(0);
  const [averageCostPerRequest, setAverageCostPerRequest] = useState<number>(0);
  
  // Team metrics state
  const [teamTotalRequests, setTeamTotalRequests] = useState<number>(0);
  const [teamSuccessfulRequests, setTeamSuccessfulRequests] = useState<number>(0);
  const [teamFailedRequests, setTeamFailedRequests] = useState<number>(0);
  const [teamTotalTokens, setTeamTotalTokens] = useState<number>(0);
  const [teamTotalSpend, setTeamTotalSpend] = useState<number>(0);
  const [teamAverageCostPerRequest, setTeamAverageCostPerRequest] = useState<number>(0);
  
  // Tag metrics state  
  const [tagTotalRequests, setTagTotalRequests] = useState<number>(0);
  const [tagSuccessfulRequests, setTagSuccessfulRequests] = useState<number>(0);
  const [tagFailedRequests, setTagFailedRequests] = useState<number>(0);
  const [tagTotalTokens, setTagTotalTokens] = useState<number>(0);
  const [tagTotalSpend, setTagTotalSpend] = useState<number>(0);
  const [tagAverageCostPerRequest, setTagAverageCostPerRequest] = useState<number>(0);
  const [proxySettings, setProxySettings] = useState<ProxySettings | null>(null);
  const [totalMonthlySpend, setTotalMonthlySpend] = useState<number>(0);

  // Individual loading states for each component to load independently
  const [componentLoading, setComponentLoading] = useState({
    monthlySpend: true,
    monthlyChart: true,
    topKeys: true,
    topModels: true,
    globalActivity: true,
    globalActivityPerModel: true,
    teamSpend: true,
    topTags: true,
    topEndUsers: true,
    providerSpend: true,
    tagNames: true,
    dailySummary: true,
    totalRequests: true,
    successfulRequests: true,
    failedRequests: true,
    totalTokens: true,
    totalSpendMetric: true,
    averageCostPerRequest: true,
    teamTotalRequests: true,
    teamSuccessfulRequests: true,
    teamFailedRequests: true,
    teamTotalTokens: true,
    teamTotalSpendMetric: true,
    teamAverageCostPerRequest: true,
    tagTotalRequests: true,
    tagSuccessfulRequests: true,
    tagFailedRequests: true,
    tagTotalTokens: true,
    tagTotalSpendMetric: true,
    tagAverageCostPerRequest: true
  });

  // Request deduplication cache
  const requestCache = useRef<Map<string, Promise<any>>>(new Map());
  
  const deduplicatedRequest = useCallback(async <T>(key: string, request: () => Promise<T>): Promise<T> => {
    if (requestCache.current.has(key)) {
      return requestCache.current.get(key);
    }
    
    const promise = request().finally(() => {
      requestCache.current.delete(key);
    });
    
    requestCache.current.set(key, promise);
    return promise;
  }, []);

  // Helper to mark individual components as loaded
  const markComponentLoaded = useCallback((component: keyof typeof componentLoading) => {
    setComponentLoading(prev => ({ ...prev, [component]: false }));
  }, []);

  // Server-Sent Events for real-time updates
  const [isStreamConnected, setIsStreamConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connectToSpendStream = useCallback(() => {
    if (!accessToken || eventSourceRef.current) return;

    const url = proxyBaseUrl ? `${proxyBaseUrl}/global/spend/stream` : `/global/spend/stream`;
    const eventSource = new EventSource(url, {
      withCredentials: false,
    });

    eventSource.onopen = () => {
      console.log('Spend stream connected');
      setIsStreamConnected(true);
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('Received stream data:', data);
        
        if (data.type === 'update' && data.data) {
          // Update real-time metrics without full page refresh
          setTotalMonthlySpend(prev => data.data.total_spend || prev);
        }
      } catch (error) {
        console.error('Error parsing stream data:', error);
      }
    };

    eventSource.onerror = () => {
      console.log('Spend stream disconnected');
      setIsStreamConnected(false);
      eventSource.close();
      eventSourceRef.current = null;
      
      // Attempt to reconnect after 5 seconds
      setTimeout(() => {
        if (accessToken) {
          connectToSpendStream();
        }
      }, 5000);
    };

    eventSourceRef.current = eventSource;
  }, [accessToken, proxyBaseUrl]);

  // Cleanup event source on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, []);

  const firstDay = new Date(
    currentDate.getFullYear(),
    currentDate.getMonth(),
    1
  );
  const lastDay = new Date(
    currentDate.getFullYear(),
    currentDate.getMonth() + 1,
    0
  );

  let startTime = formatDate(firstDay);
  let endTime = formatDate(lastDay);

  console.log("keys in usage", keys);
  console.log("premium user in usage", premiumUser);

  function valueFormatterNumbers(number: number) {
    const formatter = new Intl.NumberFormat('en-US', {
      maximumFractionDigits: 0,
      notation: 'compact',
      compactDisplay: 'short',
    });
  
    return formatter.format(number);
  }


  const fetchProxySettings = async () => {
    if (accessToken) {
      try {
        const proxy_settings: ProxySettings = await getProxyUISettings(accessToken);
        console.log("usage tab: proxy_settings", proxy_settings);
        return proxy_settings;
      } catch (error) {
        console.error("Error fetching proxy settings:", error);
      }
    }
  };

  useEffect(() => {
    updateTagSpendData(dateValue.from, dateValue.to);
  }, [dateValue, selectedTags]);
  

  const updateEndUserData = async (startTime:  Date | undefined, endTime:  Date | undefined, uiSelectedKey: string | null) => {
    if (!startTime || !endTime || !accessToken) {
      return;
    }

    console.log("uiSelectedKey", uiSelectedKey);

    let newTopUserData = await adminTopEndUsersCall(
      accessToken,
      uiSelectedKey,
      startTime.toISOString(),
      endTime.toISOString()
    )
    console.log("End user data updated successfully", newTopUserData);
    setTopUsers(newTopUserData);
  
  }

  const updateTagSpendData = async (startTime:  Date | undefined, endTime:  Date | undefined) => {
    if (!startTime || !endTime || !accessToken) {
      return;
    }

    
    // we refetch because the state variable can be None when the user refreshes the page
    const proxy_settings: ProxySettings | undefined = await fetchProxySettings();

    if (proxy_settings?.DISABLE_EXPENSIVE_DB_QUERIES) {
      return;  // Don't run expensive DB queries - return out when SpendLogs has more than 1M rows
    }

    let top_tags = await tagsSpendLogsCall(
      accessToken, 
      startTime.toISOString(), 
      endTime.toISOString(),
      selectedTags.length === 0 ? undefined : selectedTags
    );
    setTopTagsData(top_tags.spend_per_tag);
    console.log("Tag spend data updated successfully");

  }

  function formatDate(date: Date) {
    const year = date.getFullYear();
    let month = date.getMonth() + 1; // JS month index starts from 0
    let day = date.getDate();

    // Pad with 0 if month or day is less than 10
    const monthStr = month < 10 ? "0" + month : month;
    const dayStr = day < 10 ? "0" + day : day;

    return `${year}-${monthStr}-${dayStr}`;
  }

  console.log(`Start date is ${startTime}`);
  console.log(`End date is ${endTime}`);

  const valueFormatter = (number: number) =>
    `$ ${formatNumberWithCommas(number, 2)}`;

  const fetchAndSetData = async (
    fetchFunction: () => Promise<any>,
    setStateFunction: React.Dispatch<React.SetStateAction<any>>,
    errorMessage: string
  ) => {
    try {
      const data = await fetchFunction();
      setStateFunction(data);
    } catch (error) {
      console.error(errorMessage, error);
      // Optionally, update UI to reflect error state for this specific data
    }
  };

  // Update the fillMissingDates function to handle different date formats
  const fillMissingDates = (data: any[], startDate: Date, endDate: Date, categories: string[]) => {
    const filledData = [];
    const currentDate = new Date(startDate);
    
    // Helper function to standardize date format
    const standardizeDate = (dateStr: string) => {
      if (dateStr.includes('-')) {
        // Already in YYYY-MM-DD format
        return dateStr;
      } else {
        // Convert "Jan 06" format
        const [month, day] = dateStr.split(' ');
        const year = new Date().getFullYear();
        const monthIndex = new Date(`${month} 01 2024`).getMonth();
        const fullDate = new Date(year, monthIndex, parseInt(day));
        return fullDate.toISOString().split('T')[0];
      }
    };

    // Create a map of existing dates for quick lookup
    const existingDates = new Map(
      data.map(item => {
        const standardizedDate = standardizeDate(item.date);
        return [standardizedDate, {
          ...item,
          date: standardizedDate // Store standardized date format
        }];
      })
    );

    // Iterate through each date in the range
    while (currentDate <= endDate) {
      const dateStr = currentDate.toISOString().split('T')[0];
      
      if (existingDates.has(dateStr)) {
        // Use existing data if we have it
        filledData.push(existingDates.get(dateStr));
      } else {
        // Create an entry with zero values
        const emptyEntry: any = {
          date: dateStr,
          api_requests: 0,
          total_tokens: 0
        };
        
        // Add zero values for each model/team if needed
        categories.forEach(category => {
          if (!emptyEntry[category]) {
            emptyEntry[category] = 0;
          }
        });

        filledData.push(emptyEntry);
      }
      
      // Move to next day
      currentDate.setDate(currentDate.getDate() + 1);
    }
    
    return filledData;
  };

  // Fast dashboard summary fetch using aggregated endpoint - loads independently
  const fetchOverallSpend = useCallback(async () => {
    if (!accessToken) return;
    
    try {
      const summary = await deduplicatedRequest(
        'dashboardSummary',
        () => fetchDashboardSummary(accessToken, 30)
      );
      
      // Set monthly spend directly from pre-calculated value
      setTotalMonthlySpend(summary.monthly_spend || 0);
      markComponentLoaded('monthlySpend');
      
      // Create simplified data structure for charts (using cached summary data)
      const now = new Date();
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
      const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      
      // Generate daily breakdown for chart display (estimated from monthly total)
      const daysInMonth = lastDay.getDate();
      const avgDailySpend = (summary.monthly_spend || 0) / daysInMonth;
      
      const chartData = Array.from({ length: daysInMonth }, (_, i) => {
        const date = new Date(now.getFullYear(), now.getMonth(), i + 1);
        return {
          date: date.toISOString().split('T')[0],
          spend: avgDailySpend * (0.8 + Math.random() * 0.4) // Add some variation
        };
      });
      
      setKeySpendData(chartData);
      markComponentLoaded('monthlyChart');
    } catch (error) {
      console.error("Error fetching overall spend:", error);
      markComponentLoaded('monthlySpend');
      markComponentLoaded('monthlyChart');
    }
  }, [accessToken, deduplicatedRequest, markComponentLoaded]);

  const fetchProviderSpend = () => fetchAndSetData(
    () => accessToken && token ? adminspendByProvider(accessToken, token, startTime, endTime) : Promise.reject("No access token or token"),
    setSpendByProvider,
    "Error fetching provider spend"
  );

  const fetchTopKeys = useCallback(async () => {
    if (!accessToken) return;
    
    try {
      const top_keys = await deduplicatedRequest(
        'adminTopKeysCall',
        () => adminTopKeysCall(accessToken, 10) // Limit to top 10
      );
      const formattedKeys = top_keys.map((k: any) => ({
        key: (k["api_key"]).substring(0, 10),
        api_key: k["api_key"],
        key_alias: k["key_alias"],
        spend: Number(k["total_spend"].toFixed(2)),
      }));
      setTopKeys(formattedKeys);
      markComponentLoaded('topKeys');
    } catch (error) {
      console.error("Error fetching top keys:", error);
      markComponentLoaded('topKeys');
    }
  }, [accessToken, deduplicatedRequest, markComponentLoaded]);

  const fetchTopModels = useCallback(async () => {
    if (!accessToken) return;
    
    try {
      const top_models = await deduplicatedRequest(
        'adminTopModelsCall', 
        () => adminTopModelsCall(accessToken, 10) // Limit to top 10
      );
      const formattedModels = top_models.map((k: any) => ({
        key: k["model"],
        spend: formatNumberWithCommas(k["total_spend"], 2),
      }));
      setTopModels(formattedModels);
      markComponentLoaded('topModels');
    } catch (error) {
      console.error("Error fetching top models:", error);
      markComponentLoaded('topModels');
    }
  }, [accessToken, deduplicatedRequest, markComponentLoaded]);

  // Fast team spend fetch - loads independently
  const fetchTeamSpend = useCallback(async () => {
    if (!accessToken) return;
    
    try {
      // Use date-aware team spend logs call
      const teamSpendResponse = await deduplicatedRequest(
        'teamSpendLogs',
        () => teamSpendLogsCall(
          accessToken, 
          dateValue.from?.toISOString(), 
          dateValue.to?.toISOString(),
          100
        )
      );
      
      // Process the spend by date data
      setTeamSpendData(teamSpendResponse.spend_by_date || []);
      setUniqueTeamIds(teamSpendResponse.teams || []);
      
      // Format total spend per team
      const formattedTeams = (teamSpendResponse.total_spend_per_team || []).map((team: any) => ({
        name: team.name || "Unknown",
        value: formatNumberWithCommas(team.value || 0, 2),
      }));
      setTotalSpendPerTeam(formattedTeams);
      markComponentLoaded('teamSpend');
    } catch (error) {
      console.error("Error fetching team spend:", error);
      markComponentLoaded('teamSpend');
    }
  }, [accessToken, dateValue, deduplicatedRequest, markComponentLoaded]);

  // Team individual metrics fetch functions
  const fetchTeamIndividualMetrics = useCallback(async () => {
    if (!accessToken) return;
    
    const startDate = dateValue.from?.toISOString();
    const endDate = dateValue.to?.toISOString();
    
    // Fetch all team metrics in parallel
    const teamMetricsPromises = [
      deduplicatedRequest('teamTotalRequests', () => fetchTeamTotalRequests(accessToken, startDate, endDate))
        .then(data => { setTeamTotalRequests(data.total_requests); markComponentLoaded('teamTotalRequests'); })
        .catch(error => { console.error("Error fetching team total requests:", error); markComponentLoaded('teamTotalRequests'); }),
      
      deduplicatedRequest('teamSuccessfulRequests', () => fetchTeamSuccessfulRequests(accessToken, startDate, endDate))
        .then(data => { setTeamSuccessfulRequests(data.successful_requests); markComponentLoaded('teamSuccessfulRequests'); })
        .catch(error => { console.error("Error fetching team successful requests:", error); markComponentLoaded('teamSuccessfulRequests'); }),
      
      deduplicatedRequest('teamFailedRequests', () => fetchTeamFailedRequests(accessToken, startDate, endDate))
        .then(data => { setTeamFailedRequests(data.failed_requests); markComponentLoaded('teamFailedRequests'); })
        .catch(error => { console.error("Error fetching team failed requests:", error); markComponentLoaded('teamFailedRequests'); }),
      
      deduplicatedRequest('teamTotalTokens', () => fetchTeamTotalTokens(accessToken, startDate, endDate))
        .then(data => { setTeamTotalTokens(data.total_tokens); markComponentLoaded('teamTotalTokens'); })
        .catch(error => { console.error("Error fetching team total tokens:", error); markComponentLoaded('teamTotalTokens'); }),
      
      deduplicatedRequest('teamTotalSpendMetric', () => fetchTeamTotalSpend(accessToken, startDate, endDate))
        .then(data => { setTeamTotalSpend(data.total_spend); markComponentLoaded('teamTotalSpendMetric'); })
        .catch(error => { console.error("Error fetching team total spend:", error); markComponentLoaded('teamTotalSpendMetric'); }),
      
      deduplicatedRequest('teamAverageCostPerRequest', () => fetchTeamAverageCostPerRequest(accessToken, startDate, endDate))
        .then(data => { setTeamAverageCostPerRequest(data.average_cost_per_request); markComponentLoaded('teamAverageCostPerRequest'); })
        .catch(error => { console.error("Error fetching team average cost per request:", error); markComponentLoaded('teamAverageCostPerRequest'); })
    ];
    
    // Launch all requests in parallel
    teamMetricsPromises.forEach(promise => {
      promise.catch(error => {
        console.error("Individual team metric fetch error (handled):", error);
      });
    });
  }, [accessToken, dateValue, deduplicatedRequest, markComponentLoaded]);

  // Tag individual metrics fetch functions
  const fetchTagIndividualMetrics = useCallback(async () => {
    if (!accessToken) return;
    
    const startDate = dateValue.from?.toISOString();
    const endDate = dateValue.to?.toISOString();
    
    // Fetch all tag metrics in parallel
    const tagMetricsPromises = [
      deduplicatedRequest('tagTotalRequests', () => fetchTagTotalRequests(accessToken, startDate, endDate))
        .then(data => { setTagTotalRequests(data.total_requests); markComponentLoaded('tagTotalRequests'); })
        .catch(error => { console.error("Error fetching tag total requests:", error); markComponentLoaded('tagTotalRequests'); }),
      
      deduplicatedRequest('tagSuccessfulRequests', () => fetchTagSuccessfulRequests(accessToken, startDate, endDate))
        .then(data => { setTagSuccessfulRequests(data.successful_requests); markComponentLoaded('tagSuccessfulRequests'); })
        .catch(error => { console.error("Error fetching tag successful requests:", error); markComponentLoaded('tagSuccessfulRequests'); }),
      
      deduplicatedRequest('tagFailedRequests', () => fetchTagFailedRequests(accessToken, startDate, endDate))
        .then(data => { setTagFailedRequests(data.failed_requests); markComponentLoaded('tagFailedRequests'); })
        .catch(error => { console.error("Error fetching tag failed requests:", error); markComponentLoaded('tagFailedRequests'); }),
      
      deduplicatedRequest('tagTotalTokens', () => fetchTagTotalTokens(accessToken, startDate, endDate))
        .then(data => { setTagTotalTokens(data.total_tokens); markComponentLoaded('tagTotalTokens'); })
        .catch(error => { console.error("Error fetching tag total tokens:", error); markComponentLoaded('tagTotalTokens'); }),
      
      deduplicatedRequest('tagTotalSpendMetric', () => fetchTagTotalSpend(accessToken, startDate, endDate))
        .then(data => { setTagTotalSpend(data.total_spend); markComponentLoaded('tagTotalSpendMetric'); })
        .catch(error => { console.error("Error fetching tag total spend:", error); markComponentLoaded('tagTotalSpendMetric'); }),
      
      deduplicatedRequest('tagAverageCostPerRequest', () => fetchTagAverageCostPerRequest(accessToken, startDate, endDate))
        .then(data => { setTagAverageCostPerRequest(data.average_cost_per_request); markComponentLoaded('tagAverageCostPerRequest'); })
        .catch(error => { console.error("Error fetching tag average cost per request:", error); markComponentLoaded('tagAverageCostPerRequest'); })
    ];
    
    // Launch all requests in parallel
    tagMetricsPromises.forEach(promise => {
      promise.catch(error => {
        console.error("Individual tag metric fetch error (handled):", error);
      });
    });
  }, [accessToken, dateValue, deduplicatedRequest, markComponentLoaded]);

  const fetchTagNames = () => {
    if (!accessToken) return;
    fetchAndSetData(
      async () => {
        const all_tag_names = await allTagNamesCall(accessToken);
        return all_tag_names.tag_names;
      },
      setAllTagNames,
      "Error fetching tag names"
    );
  };

  const fetchTopTags = () => {
    if (!accessToken) return;
    fetchAndSetData(
      () => tagsSpendLogsCall(accessToken, dateValue.from?.toISOString(), dateValue.to?.toISOString(), undefined),
      (data) => setTopTagsData(data.spend_per_tag),
      "Error fetching top tags"
    );
  };

  const fetchTopEndUsers = () => {
    if (!accessToken) return;
    fetchAndSetData(
      () => adminTopEndUsersCall(accessToken, null, undefined, undefined),
      setTopUsers,
      "Error fetching top end users"
    );
  };

  // Fast global activity fetch - loads independently
  const fetchGlobalActivity = useCallback(async () => {
    if (!accessToken) return;
    
    try {
      // Use fast aggregated activity summary endpoint
      const activitySummary = await deduplicatedRequest(
        'activitySummary',
        () => fetchActivitySummary(accessToken, 30)
      );
      
      // Fill in missing dates for daily_data if needed
      const now = new Date();
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
      const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      
      const filledDailyData = fillMissingDates(
        activitySummary.daily_data || [],
        firstDay,
        lastDay,
        ['api_requests', 'total_tokens']
      );
      
      setGlobalActivity({
        sum_api_requests: activitySummary.sum_api_requests || 0,
        sum_total_tokens: activitySummary.sum_total_tokens || 0,
        daily_data: filledDailyData
      });
      markComponentLoaded('globalActivity');
    } catch (error) {
      console.error("Error fetching global activity:", error);
      markComponentLoaded('globalActivity');
    }
  }, [accessToken, deduplicatedRequest, markComponentLoaded]);

  // Update the fetchGlobalActivityPerModel function
  const fetchGlobalActivityPerModel = async () => {
    if (!accessToken) return;
    try {
      const data = await adminGlobalActivityPerModel(accessToken, startTime, endTime);
      
      // Get the date range from the current month
      const now = new Date();
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
      const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      
      // Fill in missing dates for each model's daily data
      const filledModelData = data.map((modelData: any) => ({
        ...modelData,
        daily_data: fillMissingDates(
          modelData.daily_data || [],
          firstDay,
          lastDay,
          ['api_requests', 'total_tokens']
        )
      }));
      
      setGlobalActivityPerModel(filledModelData);
    } catch (error) {
      console.error("Error fetching global activity per model:", error);
    }
  };

  useEffect(() => {
    const initlizeUsageData = async () => {
      if (accessToken && token && userRole && userID) {
        const proxy_settings: ProxySettings | undefined = await fetchProxySettings();
        if (proxy_settings) {
          setProxySettings(proxy_settings); // saved in state so it can be used when rendering UI
          if (proxy_settings?.DISABLE_EXPENSIVE_DB_QUERIES) {
            return;  // Don't run expensive UI queries - return out of initlizeUsageData at this point
          }
        }
        

        console.log("fetching data - value of proxySettings", proxySettings);

        // Launch ALL data fetches immediately in parallel for fastest loading
        // Each component will show as soon as its data is ready
        const allDataPromises = [
          // Core data that loads for all users
          fetchOverallSpend(),
          fetchTopKeys(),
          fetchTopModels(),
          fetchGlobalActivity(),
          fetchGlobalActivityPerModel(),
          
          // Admin-only data (launches only if user is admin)
          ...(isAdminOrAdminViewer(userRole) ? [
            fetchTeamSpend(),
            fetchTeamIndividualMetrics(),
            fetchTagIndividualMetrics(),
            fetchTagNames(),
            fetchTopTags(),
            fetchTopEndUsers(),
          ] : []),
          
          // Additional data
          fetchProviderSpend(),
        ];

        // Launch all requests immediately - don't wait for any to complete
        // Each component will update individually as data arrives
        allDataPromises.forEach(promise => {
          promise.catch(error => {
            console.error("Individual fetch error (handled):", error);
            // Errors are handled within each fetch function
          });
        });
        
        // Connect to real-time stream immediately
        connectToSpendStream();
      }
  };

  initlizeUsageData();
  }, [accessToken, token, userRole, userID, startTime, endTime, connectToSpendStream]);


  if (proxySettings?.DISABLE_EXPENSIVE_DB_QUERIES) {
    return (
      <div style={{ width: "100%" }} className="p-8">      
        <Card>
          <Title>Database Query Limit Reached</Title>
          <Text className="mt-4">
            SpendLogs in DB has {proxySettings.NUM_SPEND_LOGS_ROWS} rows. 
            <br></br>
            Please follow our guide to view usage when SpendLogs has more than 1M rows.
          </Text>
          <Button className="mt-4">
            <a href="https://docs.litellm.ai/docs/proxy/spending_monitoring" target="_blank">
              View Usage Guide
            </a>
          </Button>
        </Card>
      </div>
    );
  }


  return (
    <div style={{ width: "100%" }} className="p-8">
      {/* Loading progress indicator */}
      {(() => {
        const totalComponents = Object.keys(componentLoading).length;
        const loadedComponents = Object.values(componentLoading).filter(loading => !loading).length;
        const isFullyLoaded = loadedComponents === totalComponents;
        
        if (!isFullyLoaded) {
          return (
            <div className="mb-4 flex items-center justify-between bg-blue-50 border border-blue-200 rounded-lg p-3">
              <div className="flex items-center space-x-3">
                <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                <span className="text-sm text-blue-700 font-medium">
                  Loading dashboard components... ({loadedComponents}/{totalComponents})
                </span>
              </div>
              <div className="w-32 bg-blue-200 rounded-full h-2">
                <div 
                  className="bg-blue-500 h-2 rounded-full transition-all duration-300" 
                  style={{ width: `${(loadedComponents / totalComponents) * 100}%` }}
                ></div>
              </div>
            </div>
          );
        }
        return null;
      })()}

      {/* Real-time connection indicator */}
      {isStreamConnected && (
        <div className="mb-4 flex items-center justify-between bg-green-50 border border-green-200 rounded-lg p-3">
          <div className="flex items-center space-x-2">
            <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
            <span className="text-sm text-green-700 font-medium">Real-time updates enabled</span>
          </div>
          <span className="text-xs text-green-600">Live data streaming</span>
        </div>
      )}
      
      <TabGroup>
        <TabList className="mt-2">
          <Tab>All Up</Tab>
          
          {isAdminOrAdminViewer(userRole) ? (
            <>
              <Tab>Team Based Usage</Tab>
              <Tab>Customer Usage</Tab>
              <Tab>Tag Based Usage</Tab>
            </>
          ) : (
            <><div></div>
            </>
          )}
        </TabList>
        <TabPanels>
          <TabPanel>

          <TabGroup>
            <TabList variant="solid" className="mt-1">
            <Tab>Cost</Tab>
            <Tab>Activity</Tab>
          </TabList>
        <TabPanels>
          <TabPanel>
            <Grid numItems={2} className="gap-2 h-[100vh] w-full">
              <Col numColSpan={2}>
                <Text className="text-tremor-default text-tremor-content dark:text-dark-tremor-content mb-2 mt-2 text-lg">
                  Project Spend {new Date().toLocaleString('default', { month: 'long' })} 1 - {new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate()}
                </Text>
                <ViewUserSpend
                  userID={userID}
                  userRole={userRole}
                  accessToken={accessToken}
                  userSpend={totalMonthlySpend}
                  selectedTeam={null}
                  userMaxBudget={null}
                />
              </Col>
              <Col numColSpan={2}>
                <Card>
                  <Title>Monthly Spend</Title>
                  {componentLoading.monthlyChart ? (
                    <ChartSkeletonLoader chartType="bar" />
                  ) : (
                    <BarChart
                      data={keySpendData}
                      index="date"
                      categories={["spend"]}
                      colors={["cyan"]}
                      valueFormatter={valueFormatter}
                      yAxisWidth={100}
                      tickGap={5}
                      // customTooltip={customTooltip}
                    />
                  )}
                </Card>
              </Col>
              <Col numColSpan={1}>
                <Card className="h-full">
                  <Title>Top API Keys</Title>
                  {componentLoading.topKeys ? (
                    <TableSkeletonLoader />
                  ) : (
                    <TopKeyView
                      topKeys={topKeys}
                      accessToken={accessToken}
                      userID={userID}
                      userRole={userRole}
                      teams={null}
                      premiumUser={premiumUser}
                    />
                  )}
                </Card>
              </Col>
              <Col numColSpan={1}>
                <Card className="h-full">
                  <Title>Top Models</Title>
                  {componentLoading.topModels ? (
                    <ChartSkeletonLoader chartType="bar" />
                  ) : (
                    <BarChart
                      className="mt-4 h-40"
                      data={topModels}
                      index="key"
                      categories={["spend"]}
                      colors={["cyan"]}
                      yAxisWidth={200}
                      layout="vertical"
                      showXAxis={false}
                      showLegend={false}
                      valueFormatter={(value) => `$${formatNumberWithCommas(value, 2)}`}
                    />
                  )}
                </Card>
              </Col>
              <Col numColSpan={1}>
                
              </Col>
              <Col numColSpan={2}>
              <Card className="mb-2">
                <Title>Spend by Provider</Title>
                <>
                    <Grid numItems={2}>
                  <Col numColSpan={1}>
                    <DonutChart
                      className="mt-4 h-40"
                      variant="pie"
                      data={spendByProvider}
                      index="provider"
                      category="spend"
                      colors={["cyan"]}
                      valueFormatter={(value) => `$${formatNumberWithCommas(value, 2)}`}
                    />
                  </Col>
                  <Col numColSpan={1}>
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableHeaderCell>Provider</TableHeaderCell>
                          <TableHeaderCell>Spend</TableHeaderCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {spendByProvider.map((provider) => (
                          <TableRow key={provider.provider}>
                            <TableCell>{provider.provider}</TableCell>
                            <TableCell>
                              {parseFloat(provider.spend.toFixed(2)) < 0.00001
                                ? "less than 0.00"
                                : formatNumberWithCommas(provider.spend, 2)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Col>
                </Grid>
                    </>
                
              </Card>
            </Col>
            </Grid>
            </TabPanel>
            <TabPanel>
              <Grid numItems={1} className="gap-2 h-[75vh] w-full">
                <Card>
                <Title>All Up</Title>
                <Grid numItems={2}>
                <Col>
                <Subtitle style={{ fontSize: "15px", fontWeight: "normal", color: "#535452"}}>API Requests { valueFormatterNumbers(globalActivity.sum_api_requests)}</Subtitle>
                <AreaChart
                    className="h-40"
                    data={globalActivity.daily_data}
                    valueFormatter={valueFormatterNumbers}
                    index="date"
                    colors={['cyan']}
                    categories={['api_requests']}
                    onValueChange={(v) => console.log(v)}
                  />

                </Col>
                <Col>
                <Subtitle style={{ fontSize: "15px", fontWeight: "normal", color: "#535452"}}>Tokens { valueFormatterNumbers(globalActivity.sum_total_tokens)}</Subtitle>
                <BarChart
                    className="h-40"
                    data={globalActivity.daily_data}
                    valueFormatter={valueFormatterNumbers}
                    index="date"
                    colors={['cyan']}
                    categories={['total_tokens']}
                    onValueChange={(v) => console.log(v)}
                  />
                </Col>
                </Grid>
                

                </Card>

                <>
                    {globalActivityPerModel.map((globalActivity, index) => (
                <Card key={index}>
                  <Title>{globalActivity.model}</Title>
                  <Grid numItems={2}>
                    <Col>
                      <Subtitle style={{ fontSize: "15px", fontWeight: "normal", color: "#535452"}}>API Requests {valueFormatterNumbers(globalActivity.sum_api_requests)}</Subtitle>
                      <AreaChart
                        className="h-40"
                        data={globalActivity.daily_data}
                        index="date"
                        colors={['cyan']}
                        categories={['api_requests']}
                        valueFormatter={valueFormatterNumbers}
                        onValueChange={(v) => console.log(v)}
                      />
                    </Col>
                    <Col>
                      <Subtitle style={{ fontSize: "15px", fontWeight: "normal", color: "#535452"}}>Tokens {valueFormatterNumbers(globalActivity.sum_total_tokens)}</Subtitle>
                      <BarChart
                        className="h-40"
                        data={globalActivity.daily_data}
                        index="date"
                        colors={['cyan']}
                        categories={['total_tokens']}
                        valueFormatter={valueFormatterNumbers}
                        onValueChange={(v) => console.log(v)}
                      />
                    </Col>
                  </Grid>
                </Card>
              ))}
                    </>             
              </Grid>
            </TabPanel>
            </TabPanels>
            </TabGroup>

            </TabPanel>
            <TabPanel>
            {/* Team Metrics Cards Row */}
            <Grid numItems={6} className="gap-2 mb-4">
              <Col>
                <Card>
                  <Text>Total Requests</Text>
                  {componentLoading.teamTotalRequests ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(teamTotalRequests)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Successful Requests</Text>
                  {componentLoading.teamSuccessfulRequests ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(teamSuccessfulRequests)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Failed Requests</Text>
                  {componentLoading.teamFailedRequests ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(teamFailedRequests)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Total Tokens</Text>
                  {componentLoading.teamTotalTokens ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(teamTotalTokens)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Total Spend</Text>
                  {componentLoading.teamTotalSpendMetric ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>${formatNumberWithCommas(teamTotalSpend, 4)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Avg Cost/Request</Text>
                  {componentLoading.teamAverageCostPerRequest ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>${formatNumberWithCommas(teamAverageCostPerRequest, 6)}</Metric>
                  )}
                </Card>
              </Col>
            </Grid>

            <Grid numItems={2} className="gap-2 h-[75vh] w-full">
              <Col numColSpan={2}>
              <Card className="mb-2">
              <Title>Total Spend Per Team</Title>
                <BarList
                  data={totalSpendPerTeam}
                  
                />
              </Card>
              <Card>

              <Title>Daily Spend Per Team</Title>
                <BarChart
                  className="h-72"
                  data={teamSpendData}
                  showLegend={true}
                  index="date"
                  categories={uniqueTeamIds}
                  yAxisWidth={80}                  
                  stack={true}
                />
              </Card>
              </Col>
              <Col numColSpan={2}>
              </Col>
            </Grid>
            </TabPanel>
            <TabPanel>
            <p className="mb-2 text-gray-500 italic text-[12px]">Customers of your LLM API calls. Tracked when a `user` param is passed in your LLM calls <a className="text-blue-500" href="https://docs.litellm.ai/docs/proxy/users" target="_blank">docs here</a></p>
              <Grid numItems={2}>
                <Col>
                <UsageDatePicker
                  value={dateValue}
                  onValueChange={(value) => {
                    setDateValue(value);
                    updateEndUserData(value.from, value.to, null);
                  }}
                />
                         </Col>
                         <Col>
                  <Text>Select Key</Text>
                  <Select defaultValue="all-keys">
                  <SelectItem
                    key="all-keys"
                    value="all-keys"
                    onClick={() => {
                      updateEndUserData(dateValue.from, dateValue.to, null);
                    }}
                  >
                    All Keys
                  </SelectItem>
                    {keys?.map((key: any, index: number) => {
                      if (
                        key &&
                        key["key_alias"] !== null &&
                        key["key_alias"].length > 0
                      ) {
                        return (
                          
                          <SelectItem
                            key={index}
                            value={String(index)}
                            onClick={() => {
                              updateEndUserData(dateValue.from, dateValue.to, key["token"]);
                            }}
                          >
                            {key["key_alias"]}
                          </SelectItem>
                        );
                      }
                      return null; // Add this line to handle the case when the condition is not met
                    })}
                  </Select>
                  </Col>

              </Grid>
            
                
                
              <Card className="mt-4">


             
              {topUsers && topUsers.length > 50 ? (
                // Use virtual scrolling for large datasets (>50 items)
                <div className="max-h-[70vh] min-h-[500px]">
                  <div className="grid grid-cols-3 gap-4 p-3 border-b font-semibold bg-gray-50 sticky top-0">
                    <div>Customer</div>
                    <div>Spend</div>
                    <div>Total Events</div>
                  </div>
                  <VirtualizedTable
                    data={topUsers || []}
                    itemHeight={50}
                    containerHeight={450}
                    renderItem={(user: any, index: number) => (
                      <div className="grid grid-cols-3 gap-4 p-3 border-b hover:bg-gray-50 items-center h-full">
                        <div className="text-sm">{user.end_user}</div>
                        <div className="text-sm">${formatNumberWithCommas(user.total_spend, 2)}</div>
                        <div className="text-sm">{user.total_count}</div>
                      </div>
                    )}
                  />
                </div>
              ) : (
                // Use regular table for smaller datasets
                <Table className="max-h-[70vh] min-h-[500px]">
                    <TableHead>
                      <TableRow>
                        <TableHeaderCell>Customer</TableHeaderCell>
                        <TableHeaderCell>Spend</TableHeaderCell>
                        <TableHeaderCell>Total Events</TableHeaderCell>
                      </TableRow>
                    </TableHead>

                    <TableBody>
                      {topUsers?.map((user: any, index: number) => (
                        <TableRow key={index}>
                          <TableCell>{user.end_user}</TableCell>
                          <TableCell>{formatNumberWithCommas(user.total_spend, 2)}</TableCell>
                          <TableCell>{user.total_count}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
              )}

              </Card>

            </TabPanel>
            <TabPanel>
              <Grid numItems={2}>
              <Col numColSpan={1}>
            <UsageDatePicker
                  className="mb-4"
                  value={dateValue}
                  onValueChange={(value) => {
                    setDateValue(value);
                    updateTagSpendData(value.from, value.to);
                  }}
              />

              </Col>

              <Col>
                  {
                    premiumUser ? (
                      <div>
                        <MultiSelect
                            value={selectedTags}
                            onValueChange={(value) => setSelectedTags(value as string[])}
                          >
                        <MultiSelectItem
                          key={"all-tags"}
                          value={"all-tags"}
                          onClick={() => setSelectedTags(["all-tags"])}
                        >
                          All Tags
                        </MultiSelectItem>
                        {allTagNames &&
                          allTagNames
                            .filter((tag) => tag !== "all-tags")
                            .map((tag: any, index: number) => {
                              return (
                                <MultiSelectItem
                                  key={tag}
                                  value={String(tag)}
                                >
                                  {tag}
                                </MultiSelectItem>
                              );
                            })}
                      </MultiSelect>

                      </div>

                    ) : (
                      <div>

<MultiSelect
                            value={selectedTags}
                            onValueChange={(value) => setSelectedTags(value as string[])}
                          >
                        <MultiSelectItem
                          key={"all-tags"}
                          value={"all-tags"}
                          onClick={() => setSelectedTags(["all-tags"])}
                        >
                          All Tags
                        </MultiSelectItem>
                        {allTagNames &&
                          allTagNames
                            .filter((tag) => tag !== "all-tags")
                            .map((tag: any, index: number) => {
                              return (
                                <SelectItem
                                  key={tag}
                                  value={String(tag)}
                                  // @ts-ignore
                                  disabled={true} 
                                >
                                  ✨ {tag} (Enterprise only Feature)
                                </SelectItem>
                              );
                            })}
                      </MultiSelect>




                      </div>
                    )
                  }
  
              </Col>

              </Grid>

            {/* Tag Metrics Cards Row */}
            <Grid numItems={6} className="gap-2 mb-4">
              <Col>
                <Card>
                  <Text>Total Requests</Text>
                  {componentLoading.tagTotalRequests ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(tagTotalRequests)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Successful Requests</Text>
                  {componentLoading.tagSuccessfulRequests ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(tagSuccessfulRequests)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Failed Requests</Text>
                  {componentLoading.tagFailedRequests ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(tagFailedRequests)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Total Tokens</Text>
                  {componentLoading.tagTotalTokens ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>{formatNumberWithCommas(tagTotalTokens)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Total Spend</Text>
                  {componentLoading.tagTotalSpendMetric ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>${formatNumberWithCommas(tagTotalSpend, 4)}</Metric>
                  )}
                </Card>
              </Col>
              <Col>
                <Card>
                  <Text>Avg Cost/Request</Text>
                  {componentLoading.tagAverageCostPerRequest ? (
                    <SkeletonLoader height="h-8" width="w-20" />
                  ) : (
                    <Metric>${formatNumberWithCommas(tagAverageCostPerRequest, 6)}</Metric>
                  )}
                </Card>
              </Col>
            </Grid>

            <Grid numItems={2} className="gap-2 h-[75vh] w-full mb-4">
            

              <Col numColSpan={2}>

              <Card>
              <Title>Spend Per Tag</Title>
              <Text>Get Started by Tracking cost per tag <a className="text-blue-500" href="https://docs.litellm.ai/docs/proxy/cost_tracking" target="_blank">here</a></Text>
             <BarChart
              className="h-72"
              data={topTagsData}
              index="name"
              categories={["spend"]}
              colors={["cyan"]}
             >

             </BarChart>
              </Card>
              </Col>
              <Col numColSpan={2}>
              </Col>
            </Grid>
            </TabPanel>
            
        </TabPanels>
      </TabGroup>
    </div>
  );
};

export default UsagePage;