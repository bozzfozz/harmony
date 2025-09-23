import api from "./api";

type ActivityItem = {
  id: string;
  event: string;
  service: string;
  timestamp: string;
};

const activityService = {
  getRecentActivity: async (): Promise<ActivityItem[]> => {
    const { data } = await api.get("/activity/recent");
    return data.activities ?? data;
  }
};

export type { ActivityItem };
export default activityService;
