// jpcite Office Add-in webpack config.
// Bundles src/functions.ts -> dist/functions.js for the custom-functions runtime.
const path = require("path");

module.exports = (_env, argv) => ({
  mode: argv && argv.mode === "production" ? "production" : "development",
  devtool: argv && argv.mode === "production" ? false : "source-map",
  entry: {
    functions: "./src/functions.ts",
  },
  output: {
    path: path.resolve(__dirname, "dist"),
    filename: "[name].js",
    library: { type: "var", name: "jpcite" },
    clean: true,
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: "ts-loader",
      },
    ],
  },
});
