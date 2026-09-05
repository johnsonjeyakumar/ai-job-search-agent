export const EXPERIENCE_LEVELS = [
  "Fresher",
  "0-2 years",
  "2-4 years",
  "4-6 years",
  "6+ years",
];

export const TARGET_ROLES = [
  "Software Developer",
  "Full Stack Developer",
  "Frontend Developer",
  "Backend Developer",
  "Java Developer",
  "React Developer",
  "Junior Software Engineer",
  "Technical Support Engineer",
];

export const DEFAULT_LOCATIONS = ["Chennai", "Madurai", "Remote - India"];

export const REMOTE_TYPES = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
};

export const EMPLOYMENT_TYPES = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  internship: "Internship",
};

export const NOTICE_PERIODS = [
  "Immediate",
  "15 days",
  "30 days",
  "60 days",
  "90 days",
];

export const WORK_AUTHORIZATIONS = ["Indian Citizen"];

export function validateProfileUrl(value) {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return "URL must start with http:// or https://";
    }
    return null;
  } catch {
    return "Enter a valid URL including the protocol (e.g. https://github.com/user)";
  }
}

export function validateGraduationYear(value) {
  if (!value) return null;
  const year = Number(value);
  if (!Number.isInteger(year) || year < 1950 || year > 2100) {
    return "Enter a year between 1950 and 2100";
  }
  return null;
}