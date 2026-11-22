// 모든 경로를 같은 경로의 Pages 주소로 301 이동 (검색엔진도 새 주소로 옮겨 감)
const TARGET = "https://gov-grants.pages.dev";

export default {
  fetch(request) {
    const url = new URL(request.url);
    return Response.redirect(TARGET + url.pathname + url.search, 301);
  },
};
