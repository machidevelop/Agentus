import packageJson from "../../package.json";

const currentYear = new Date().getFullYear();

export const APP_CONFIG = {
  name: "Natilah",
  version: packageJson.version,
  copyright: `© ${currentYear}, Natilah.`,
  meta: {
    title: "Natilah — GPU Infrastructure Intelligence",
    description:
      "AI-powered GPU compute economics intelligence. Discover waste, recover capacity, optimize allocation.",
  },
};
