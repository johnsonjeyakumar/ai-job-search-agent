export default function Input(props) {
  const { invalid = false, className = "", ...rest } = props;
  return (
    <input
      {...rest}
      className={`w-full rounded border bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:ring-2 ${
        invalid
          ? "border-red-400 focus:border-red-500 focus:ring-red-100"
          : "border-slate-300 focus:border-slate-500 focus:ring-slate-100"
      } ${className}`}
    />
  );
}