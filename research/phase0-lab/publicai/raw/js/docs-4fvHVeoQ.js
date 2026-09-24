import{u as r,j as e}from"./entry.client-ChJ0-kRF.js";const h="Welcome to the Public AI Inference Utility developer portal.",d=[{depth:1,value:"Quick Start",id:"quick-start",children:[{depth:2,value:"1. Get your API key",id:"1-get-your-api-key"},{depth:2,value:"2. Explore available models",id:"2-explore-available-models"},{depth:2,value:"3. Make your first request",id:"3-make-your-first-request"},{depth:2,value:"Authentication",id:"authentication"},{depth:2,value:"Model configuration",id:"model-configuration"},{depth:2,value:"Rate limits and billing",id:"rate-limits-and-billing"},{depth:2,value:"Support",id:"support"},{depth:2,value:"What's next?",id:"whats-next"}]}],c={lastModifiedTime:"2026-09-24T13:34:30.000Z"},o="pages/docs.mdx";function l(s){const i={a:"a",code:"code",em:"em",h1:"h1",h2:"h2",li:"li",ol:"ol",p:"p",pre:"pre",span:"span",strong:"strong",ul:"ul",...r(),...s.components},{OpenPlaygroundButton:n}=i;return n||a("OpenPlaygroundButton"),e.jsxs(e.Fragment,{children:[e.jsx(i.h1,{id:"quick-start",children:"Quick Start"}),`
`,e.jsx(i.p,{children:"Welcome to the Public AI Inference Utility developer portal."}),`
`,e.jsx(i.h2,{id:"1-get-your-api-key",children:"1. Get your API key"}),`
`,e.jsx(i.p,{children:"Every new user account receives $2 of free starter credit, used for API calls at the listed per-token prices."}),`
`,e.jsxs(i.ol,{children:[`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"Sign up"}),": Click ",e.jsx(i.a,{href:"/signin",children:"Login"})," in the top right and sign up"]}),`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"Open Account"}),": Go to the ",e.jsx(i.a,{href:"/account/billing",children:"Account"})," tab in the top navigation"]}),`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"Create API key"}),": Open ",e.jsx(i.a,{href:"/settings/api-keys",children:"API Keys"})," and click ",e.jsx(i.em,{children:"Create API Key"})]}),`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"Generate"}),": Enter a name, set expiration, and click ",e.jsx(i.em,{children:"Generate Key"})]}),`
`]}),`
`,e.jsx(i.h2,{id:"2-explore-available-models",children:"2. Explore available models"}),`
`,e.jsxs(i.p,{children:["See ",e.jsx(i.a,{href:"/models",children:"Available Models"})," for the full catalog of hosted models, including Swiss AI Apertus, AISingapore SEA-LION, Allen AI Olmo, and more."]}),`
`,e.jsx(i.p,{children:"You can also list models programmatically:"}),`
`,e.jsx(e.Fragment,{children:e.jsx(i.pre,{children:e.jsxs(i.code,{className:"language-bash shiki shiki-themes github-light github-dark",inline:"false",style:{"--shiki-light":"#24292e","--shiki-dark":"#e1e4e8","--shiki-light-bg":"#fff","--shiki-dark-bg":"#24292e"},tabIndex:"0",children:[e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#6F42C1","--shiki-dark":"#B392F0"},children:"curl"}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" -X"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:" GET"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:" https://api.publicai.co/v1/models"}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" \\"})]}),`
`,e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:"  -H"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:' "Authorization: Bearer YOUR_API_KEY"'}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" \\"})]}),`
`,e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:"  -H"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:' "User-Agent: MyApp/1.0"'})]})]})})}),`
`,e.jsx(i.p,{children:e.jsx(i.strong,{children:"Or try it interactively:"})}),`
`,e.jsx(n,{server:"https://api.publicai.co/",url:"/v1/models",method:"GET",headers:[{name:"Authorization",defaultValue:"Bearer YOUR_API_KEY_HERE"},{name:"User-Agent",defaultValue:"MyApp/1.0"}]}),`
`,e.jsx(i.h2,{id:"3-make-your-first-request",children:"3. Make your first request"}),`
`,e.jsx(i.p,{children:"Once you have an API key, you can start making requests to our AI models. Here's a simple example:"}),`
`,e.jsx(e.Fragment,{children:e.jsx(i.pre,{children:e.jsxs(i.code,{className:"language-bash shiki shiki-themes github-light github-dark",inline:"false",style:{"--shiki-light":"#24292e","--shiki-dark":"#e1e4e8","--shiki-light-bg":"#fff","--shiki-dark-bg":"#24292e"},tabIndex:"0",children:[e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#6F42C1","--shiki-dark":"#B392F0"},children:"curl"}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" -X"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:" POST"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:" https://api.publicai.co/v1/chat/completions"}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" \\"})]}),`
`,e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:"  -H"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:' "Content-Type: application/json"'}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" \\"})]}),`
`,e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:"  -H"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:' "Authorization: Bearer YOUR_API_KEY"'}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" \\"})]}),`
`,e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:"  -H"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:' "User-Agent: MyApp/1.0"'}),e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:" \\"})]}),`
`,e.jsxs(i.span,{className:"line",children:[e.jsx(i.span,{style:{"--shiki-light":"#005CC5","--shiki-dark":"#79B8FF"},children:"  -d"}),e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:" '{"})]}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:'    "model": "swiss-ai/apertus-v1.5-8b",'})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:'    "messages": ['})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:"      {"})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:'        "role": "user",'})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:'        "content": "Hello! Can you help me understand open-source AI?"'})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:"      }"})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:"    ]"})}),`
`,e.jsx(i.span,{className:"line",children:e.jsx(i.span,{style:{"--shiki-light":"#032F62","--shiki-dark":"#9ECBFF"},children:"  }'"})})]})})}),`
`,e.jsx(i.p,{children:e.jsx(i.strong,{children:"Or try it interactively:"})}),`
`,e.jsx(n,{server:"https://api.publicai.co/",url:"/v1/chat/completions",method:"POST",headers:[{name:"Authorization",defaultValue:"Bearer YOUR_API_KEY_HERE"},{name:"User-Agent",defaultValue:"MyApp/1.0"},{name:"Content-Type",defaultValue:"application/json"}],body:JSON.stringify({model:"swiss-ai/apertus-v1.5-8b",messages:[{role:"user",content:"Hello! Can you help me understand open-source AI?"}]})}),`
`,e.jsx(i.h2,{id:"authentication",children:"Authentication"}),`
`,e.jsx(i.p,{children:"All API requests require:"}),`
`,e.jsxs(i.ol,{children:[`
`,e.jsxs(i.li,{children:[`
`,e.jsxs(i.p,{children:[e.jsx(i.strong,{children:"API Key"}),": Include your key in the Authorization header:"]}),`
`,e.jsx(e.Fragment,{children:e.jsx(i.pre,{children:e.jsx(i.code,{className:"language-text shiki shiki-themes github-light github-dark",inline:"false",style:{"--shiki-light":"#24292e","--shiki-dark":"#e1e4e8","--shiki-light-bg":"#fff","--shiki-dark-bg":"#24292e"},tabIndex:"0",children:e.jsx(i.span,{className:"line",children:e.jsx(i.span,{children:"Authorization: Bearer YOUR_API_KEY"})})})})}),`
`]}),`
`,e.jsxs(i.li,{children:[`
`,e.jsxs(i.p,{children:[e.jsx(i.strong,{children:"User-Agent Header"}),": Specify a User-Agent to prevent bot spamming:"]}),`
`,e.jsx(e.Fragment,{children:e.jsx(i.pre,{children:e.jsx(i.code,{className:"language-text shiki shiki-themes github-light github-dark",inline:"false",style:{"--shiki-light":"#24292e","--shiki-dark":"#e1e4e8","--shiki-light-bg":"#fff","--shiki-dark-bg":"#24292e"},tabIndex:"0",children:e.jsx(i.span,{className:"line",children:e.jsx(i.span,{children:"User-Agent: MyApp/1.0"})})})})}),`
`]}),`
`]}),`
`,e.jsx(i.h2,{id:"model-configuration",children:"Model configuration"}),`
`,e.jsxs(i.p,{children:["Inference parameters vary by model. See each model's Hugging Face card on the ",e.jsx(i.a,{href:"/models",children:"Available Models"})," page, and use ",e.jsx(i.code,{inline:"true",children:"GET /v1/models"})," for ",e.jsx(i.code,{inline:"true",children:"context_length"})," and pricing."]}),`
`,e.jsx(i.h2,{id:"rate-limits-and-billing",children:"Rate limits and billing"}),`
`,e.jsxs(i.p,{children:["Rate limits depend on your plan tier. See ",e.jsx(i.a,{href:"/plans",children:"Plans & Rate Limits"})," for details on Free, Plus, Pro, and Enterprise tiers. Usage and wallet balance are available under Account → ",e.jsx(i.a,{href:"/account/billing",children:"Billing"}),"."]}),`
`,e.jsx(i.h2,{id:"support",children:"Support"}),`
`,e.jsxs(i.ul,{children:[`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"API Reference:"})," Explore the full ",e.jsx(i.a,{href:"/api",children:"API Reference"})]}),`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"Community:"})," Join our discussions at ",e.jsx(i.a,{href:"https://github.com/forpublicai",children:"github.com/forpublicai"})]}),`
`,e.jsxs(i.li,{children:[e.jsx(i.strong,{children:"Issues:"})," Report problems via GitHub Issues"]}),`
`]}),`
`,e.jsx(i.h2,{id:"whats-next",children:"What's next?"}),`
`,e.jsxs(i.ul,{children:[`
`,e.jsxs(i.li,{children:["Browse ",e.jsx(i.a,{href:"/models",children:"Available Models"})," and pick the right model for your use case"]}),`
`,e.jsxs(i.li,{children:["Review ",e.jsx(i.a,{href:"/plans",children:"Plans & Rate Limits"})," and ",e.jsx(i.a,{href:"/account/billing",children:"Billing"})," for usage and pricing"]}),`
`,e.jsxs(i.li,{children:["Explore the complete ",e.jsx(i.a,{href:"/api",children:"API Reference"})," for detailed endpoint documentation"]}),`
`,e.jsxs(i.li,{children:[e.jsx(i.a,{href:"/support-us",children:"Support Us"})," to upgrade to the Plus tier via OpenCollective"]}),`
`]})]})}function p(s={}){const{wrapper:i}={...r(),...s.components};return i?e.jsx(i,{...s,children:e.jsx(l,{...s})}):l(s)}function a(s,i){throw new Error("Expected component `"+s+"` to be defined: you likely forgot to import, pass, or provide it.")}export{o as __filepath,p as default,h as excerpt,c as frontmatter,d as tableOfContents};
//# sourceMappingURL=docs-4fvHVeoQ.js.map
