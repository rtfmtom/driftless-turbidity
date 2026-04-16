FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY tsconfig.json next.config.mjs postcss.config.mjs tailwind.config.ts .eslintrc.json ./
COPY app ./app
COPY components ./components
COPY lib ./lib
COPY public ./public

EXPOSE 3000

CMD ["npm", "run", "dev"]
